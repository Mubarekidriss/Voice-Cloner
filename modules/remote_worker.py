"""Bounded server-to-server client. No model imports, redirects or browser tokens."""
import base64
import binascii
import json
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from django.conf import settings
from config import LANGUAGES
from local_worker import MAX_AUDIO, MAX_OUTPUT, MAX_TEXT, check_wav, RequestError

MAX_RESPONSE = 2 * (((MAX_OUTPUT + 2) // 3) * 4) + 4096

class RemoteWorkerError(ValueError):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

class RemoteService:
    device = 'remote worker (not health-checked)'
    available_languages = ()  # Configuration is not proof a model is loaded.

    def generate_voices(self, text, reference, language):
        url = settings.VOICE_WORKER_URL
        secret = settings.VOICE_WORKER_SECRET
        parsed = urlsplit(url)
        loopback = parsed.hostname in ('127.0.0.1', '::1', 'localhost')
        if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback and settings.VOICE_WORKER_ALLOW_LOOPBACK)) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise RemoteWorkerError('Worker URL must be an HTTPS origin. Local test HTTP needs explicit loopback permission.')
        if len(secret) < 32 or not secret.isascii() or any(ord(x) < 33 or ord(x) > 126 for x in secret):
            raise RemoteWorkerError('A private worker key of at least 32 printable ASCII characters is required.')
        if not text.strip() or len(text) > MAX_TEXT or language not in LANGUAGES:
            raise RemoteWorkerError('Choose a supported language and use 1 to 2000 text characters.')
        reference = Path(reference)
        if not 0 < reference.stat().st_size <= MAX_AUDIO:
            raise RemoteWorkerError('Reference audio exceeds the size limit or is empty.')
        audio = reference.read_bytes()
        try:
            check_wav(audio, reference=True)
        except RequestError as exc:
            raise RemoteWorkerError('Normalize a valid 6 to 30 second PCM WAV first.') from exc
        body = json.dumps({'text': text.strip(), 'language': language, 'consent': True,
            'reference_wav_base64': base64.b64encode(audio).decode('ascii')}).encode()
        request = Request(url.rstrip('/') + '/generate', data=body,
            headers={'Content-Type': 'application/json', 'X-Worker-Secret': secret}, method='POST')
        try:
            # Do not inherit system proxies or follow a redirect carrying the key/audio.
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=settings.VOICE_WORKER_TIMEOUT) as response:
                if response.status != 200 or response.headers.get_content_type() != 'application/json':
                    raise RemoteWorkerError('Worker returned an unexpected response.')
                data = response.read(MAX_RESPONSE + 1)
                if len(data) > MAX_RESPONSE:
                    raise RemoteWorkerError('Worker response exceeds the size limit.')
        except HTTPError as exc:
            errors = {401: 'Worker key was rejected. Check private configuration.',
                      503: 'The model computer is busy. Try again after its current request.',
                      400: 'The worker rejected this audio or text. Check the sample and try again.'}
            raise RemoteWorkerError(errors.get(exc.code, 'Worker could not generate both outputs. No audio was saved.')) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise RemoteWorkerError('The model computer is unavailable or timed out. Check that the worker and connection are running.') from exc
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict) or set(payload) != {'baseline_wav_base64', 'clone_wav_base64'}:
                raise ValueError('fields')
            outputs = []
            for field in ('baseline_wav_base64', 'clone_wav_base64'):
                value = payload[field]
                if not isinstance(value, str) or len(value) > ((MAX_OUTPUT + 2) // 3) * 4:
                    raise ValueError('size')
                audio = base64.b64decode(value, validate=True)
                if len(audio) > MAX_OUTPUT:
                    raise ValueError('size')
                check_wav(audio)
                outputs.append(audio)
        except (ValueError, TypeError, binascii.Error, RequestError) as exc:
            raise RemoteWorkerError('Worker returned invalid audio. No audio was saved.') from exc
        paths = []
        try:
            for audio in outputs:
                with tempfile.NamedTemporaryFile(suffix='.wav', prefix='voice_remote_', delete=False) as handle:
                    paths.append(handle.name)
                    handle.write(audio)
            return tuple(paths)
        except BaseException:
            for path in paths:
                Path(path).unlink(missing_ok=True)
            raise
