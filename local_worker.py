"""Loopback-only FP11 worker prototype. No tunnel or Django configuration is made.

Requires WORKER_SECRET_KEY (at least 32 characters). Model dependencies are imported
only for an authenticated, validated generation. No model licence is auto-accepted.
"""
from __future__ import annotations
import argparse
import base64
import binascii
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import wave
from types import SimpleNamespace
from config import LANGUAGES

MAX_AUDIO = 25 * 1024 * 1024
MAX_BODY = ((MAX_AUDIO + 2) // 3) * 4 + 64 * 1024
MAX_OUTPUT = 25 * 1024 * 1024
MAX_TEXT = 2000
DEVICES = ('auto', 'cpu', 'cuda', 'rocm', 'xpu', 'mps')


class RequestError(ValueError):
    pass


def check_wav(data: bytes, reference=False) -> None:
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            rate = audio.getframerate()
            duration = audio.getnframes() / rate if rate else 0
            if (audio.getcomptype() != 'NONE' or not audio.readframes(1)
                    or not 1 <= audio.getnchannels() <= 2
                    or audio.getsampwidth() not in (1, 2, 3, 4)
                    or not 8000 <= rate <= 192000):
                raise RequestError('A readable PCM WAV is required.')
            if reference and not 6 <= duration <= 30:
                raise RequestError('Reference duration must be 6 to 30 seconds.')
            if not reference and duration <= 0:
                raise RequestError('Generated audio is empty.')
            expected = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            if expected > len(data) or len(audio.readframes(audio.getnframes())) < max(0, expected - audio.getnchannels()*audio.getsampwidth()):
                raise RequestError('WAV data is truncated.')
    except (wave.Error, EOFError, OSError, ZeroDivisionError) as exc:
        raise RequestError('A readable PCM WAV is required.') from exc


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RequestError('Duplicate JSON fields are not supported.')
        value[key] = item
    return value


def decode_request(body: bytes):
    try:
        payload = json.loads(body, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise RequestError('Invalid JSON.') from exc
    if not isinstance(payload, dict) or set(payload) != {'text', 'language', 'consent', 'reference_wav_base64'}:
        raise RequestError('Use exactly text, language, consent and reference_wav_base64.')
    if payload['consent'] is not True:
        raise RequestError('Voice-owner permission must be confirmed for each request.')
    text = payload['text']
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or '\x00' in text:
        raise RequestError('Text must contain 1 to 2000 characters, without NUL.')
    language = payload['language']
    if not isinstance(language, str):
        raise RequestError('Unsupported language.')
    names = {v: k for k, v in LANGUAGES.items()}
    language = names.get(language, language)
    if language not in LANGUAGES:
        raise RequestError('Unsupported language.')
    encoded = payload['reference_wav_base64']
    if not isinstance(encoded, str) or len(encoded) > ((MAX_AUDIO + 2) // 3) * 4:
        raise RequestError('Reference exceeds the 25 MiB limit.')
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RequestError('Invalid audio encoding.') from exc
    if not audio or len(audio) > MAX_AUDIO:
        raise RequestError('Reference exceeds the 25 MiB limit or is empty.')
    check_wav(audio, reference=True)
    return text.strip(), language, audio


def generate_pair(text, language, audio, device):
    from local_inference import run
    # One directory owns uploaded, normalized, and returned files for this request.
    # The helper owns its normalized/engine temps; this owns its input and copies.
    with tempfile.TemporaryDirectory(prefix='voice_worker_') as tmp:
        root = Path(tmp)
        reference = root / 'reference.wav'
        reference.write_bytes(audio)
        result = run(SimpleNamespace(reference=reference, text=text, language=language,
                                    device=device, output_dir=root / 'outputs', consent=True))
        pair = []
        for name in ('baseline.wav', 'clone.wav'):
            path = result / name
            if path.stat().st_size > MAX_OUTPUT:
                raise RequestError('Generated output exceeds the size limit.')
            data = path.read_bytes()
            check_wav(data)
            pair.append(data)
        return tuple(pair)


class WorkerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 4

    def __init__(self, address, secret, device='auto', runner=generate_pair):
        if address[0] not in ('127.0.0.1', '::1'):
            raise ValueError('Worker must bind to loopback; public exposure is not enabled.')
        if not isinstance(secret, str) or len(secret) < 32 or not secret.isascii():
            raise ValueError('Set WORKER_SECRET_KEY to a secret of at least 32 ASCII characters.')
        if device not in DEVICES:
            raise ValueError('Unsupported device.')
        self.secret = secret
        self.device = device
        self.runner = runner
        self.generation_lock = threading.Lock()
        self.clients = threading.BoundedSemaphore(8)
        super().__init__(address, WorkerHandler)

    def process_request(self, request, client_address):
        if not self.clients.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.clients.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.clients.release()


class WorkerHandler(BaseHTTPRequestHandler):
    server_version = 'VoiceWorker'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # No voice content, tokens, text or client metadata in access logs.

    def reply(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass

    def do_POST(self):
        # No browser CORS support; only the authenticated server-to-server contract.
        if self.path != '/generate':
            self.reply(404, {'error': 'Not found.'})
            return
        tokens = self.headers.get_all('X-Worker-Secret', [])
        if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode('utf-8'), self.server.secret.encode('ascii')):
            self.reply(401, {'error': 'Unauthorized.'})
            return
        if self.headers.get('Origin'):
            self.reply(403, {'error': 'Browser-origin requests are not supported.'})
            return
        if self.headers.get_content_type() != 'application/json':
            self.reply(415, {'error': 'Use application/json.'})
            return
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or len(lengths[0]) > 12 or not lengths[0].isascii() or not lengths[0].isdigit() or self.headers.get('Transfer-Encoding'):
            self.reply(411, {'error': 'One valid Content-Length is required; no transfer encoding.'})
            return
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            self.reply(413, {'error': 'Request exceeds the size limit or is empty.'})
            return
        if not self.server.generation_lock.acquire(blocking=False):
            self.reply(503, {'error': 'Worker busy. Try again after the current request finishes.'})
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise RequestError('Incomplete request.')
            text, language, audio = decode_request(body)
            baseline, clone = self.server.runner(text, language, audio, self.server.device)
            # Check injected and real runner outputs identically.
            for item in (baseline, clone):
                if len(item) > MAX_OUTPUT:
                    raise RequestError('Generated output exceeds the size limit.')
                check_wav(item)
            self.reply(200, {'baseline_wav_base64': base64.b64encode(baseline).decode('ascii'),
                             'clone_wav_base64': base64.b64encode(clone).decode('ascii')})
        except RequestError as exc:
            self.reply(400, {'error': str(exc)})
        except (socket.timeout, TimeoutError):
            self.reply(408, {'error': 'Request timed out.'})
        except Exception:
            self.reply(500, {'error': 'Generation failed. Check local model setup; no audio was returned.'})
        finally:
            self.server.generation_lock.release()

    def do_GET(self):
        self.reply(405, {'error': 'Use POST /generate.'})

    do_OPTIONS = do_GET


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--device', choices=DEVICES, default='auto')
    args = parser.parse_args(argv)
    secret = os.environ.get('WORKER_SECRET_KEY', '')
    try:
        server = WorkerServer(('127.0.0.1', args.port), secret, args.device)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f'Worker listening on loopback port {server.server_port}. No public tunnel is started.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
