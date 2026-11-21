"""FP11 contract tests: synthetic PCM and fake generation only, no XTTS download."""
import array
import base64
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from types import ModuleType
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_worker as worker

# Deliberately public test-only string, never a deployment credential.
TEST_TOKEN = 'test-only-placeholder-not-a-real-secret'


def wav(seconds=7):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(array.array('h', [2000, -2000] * (8000 * seconds // 2)).tobytes())
    return output.getvalue()


def payload(**updates):
    value = {'text': '  Hello  ', 'language': 'en', 'consent': True,
             'reference_wav_base64': base64.b64encode(wav()).decode()}
    value.update(updates)
    return value


class ValidationTests(unittest.TestCase):
    def test_supported_language_and_trim(self):
        text, language, audio = worker.decode_request(json.dumps(payload()).encode())
        self.assertEqual((text, language), ('Hello', 'English'))
        self.assertEqual(audio, wav())

    def test_invalid_payloads(self):
        invalid = [b'[]', b'null', b'{', b'\xff', b'{}', b'{"text":"a","text":"b"}']
        for update in ({'consent': False}, {'consent': 1}, {'text': ''}, {'text': ' '},
                       {'text': 'a'*2001}, {'text': 'a\x00'}, {'language': 'xx'},
                       {'language': []}, {'reference_wav_base64': '!!!'},
                       {'reference_wav_base64': ''}, {'extra': True}):
            invalid.append(json.dumps(payload(**update)).encode())
        for item in invalid:
            with self.subTest(item=item[:40]), self.assertRaises(worker.RequestError):
                worker.decode_request(item)

    def test_invalid_wavs(self):
        for audio in (b'bad', wav(1), wav(31), wav()[:-20]):
            with self.subTest(length=len(audio)), self.assertRaises(worker.RequestError):
                worker.decode_request(json.dumps(payload(reference_wav_base64=base64.b64encode(audio).decode())).encode())

    def test_bind_and_secret_fail_closed(self):
        for address, token in [(('0.0.0.0',0), TEST_TOKEN), (('127.0.0.1',0), ''),
                               (('127.0.0.1',0), 'short')]:
            with self.assertRaises(ValueError):
                worker.WorkerServer(address, token)

    def test_no_heavy_imports_for_help_or_module(self):
        import subprocess
        code = 'import sys,local_worker; assert not any(x in sys.modules for x in ("torch","TTS","django"))'
        subprocess.run([sys.executable,'-c',code],check=True,cwd=Path(worker.__file__).parent)
        result = subprocess.run([sys.executable,worker.__file__,'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertIn('--device',result.stdout)



class CleanupTests(unittest.TestCase):
    def run_fake_helper(self, fail=False):
        fake = ModuleType('local_inference')
        touched=[]
        def run(args):
            touched.append(args.reference.parent)
            self.assertTrue(args.reference.is_file())
            if fail:
                raise RuntimeError('simulated failure')
            dest=args.output_dir/'run_test'
            dest.mkdir(parents=True)
            for name in ('baseline.wav','clone.wav'):
                (dest/name).write_bytes(wav(1))
            return dest
        fake.run=run
        with patch.dict(sys.modules, {'local_inference':fake}):
            if fail:
                with self.assertRaises(RuntimeError):worker.generate_pair('hi','English',wav(),'cpu')
            else:
                pair=worker.generate_pair('hi','English',wav(),'cpu')
                self.assertEqual(pair,(wav(1),wav(1)))
        self.assertTrue(touched)
        self.assertFalse(touched[0].exists())

    def test_success_removes_input_and_outputs(self):self.run_fake_helper()
    def test_failure_removes_input_and_outputs(self):self.run_fake_helper(fail=True)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def fake(*args):
            self.calls.append(args)
            return wav(1),wav(1)
        self.server=worker.WorkerServer(('127.0.0.1',0),TEST_TOKEN,runner=fake)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self, body=None, headers=None, method='POST', path='/generate'):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        data=json.dumps(payload()).encode() if body is None else body
        fields={'Content-Type':'application/json','X-Worker-Secret':TEST_TOKEN}
        if headers: fields.update(headers)
        connection.request(method,path,body=data,headers=fields)
        response=connection.getresponse()
        status=response.status;result=json.loads(response.read())
        self.assertEqual(response.getheader('Cache-Control'),'no-store')
        connection.close()
        return status,result

    def test_loopback_round_trip(self):
        status,result=self.request()
        self.assertEqual(status,200)
        self.assertEqual(set(result),{'baseline_wav_base64','clone_wav_base64'})
        worker.check_wav(base64.b64decode(result['clone_wav_base64']))
        self.assertEqual(self.calls[0][:2],('Hello','English'))

    def test_unauthorized_never_runs(self):
        self.assertEqual(self.request(headers={'X-Worker-Secret':'wrong'})[0],401)
        self.assertFalse(self.calls)

    def test_cross_origin_rejected(self):
        self.assertEqual(self.request(headers={'Origin':'https://example.invalid'})[0],403)
        self.assertFalse(self.calls)

    def test_wrong_route_and_methods(self):
        self.assertEqual(self.request(path='/other')[0],404)
        self.assertEqual(self.request(method='GET')[0],405)
        self.assertEqual(self.request(method='OPTIONS')[0],405)

    def test_body_headers(self):
        for headers,status in [({'Content-Type':'text/plain'},415),
                               ({'Content-Length':str(worker.MAX_BODY+1)},413),
                               ({'Transfer-Encoding':'chunked'},411),
                               ({'Content-Length':'invalid'},411), ({'Content-Length':'9'*5000},411)]:
            with self.subTest(headers=headers): self.assertEqual(self.request(headers=headers)[0],status)
        self.assertFalse(self.calls)

    def test_bad_request_then_valid_lock_released(self):
        self.assertEqual(self.request(body=b'{}')[0],400)
        self.assertEqual(self.request()[0],200)

    def test_busy_rejected(self):
        self.server.generation_lock.acquire()
        try: self.assertEqual(self.request()[0],503)
        finally: self.server.generation_lock.release()
        self.assertFalse(self.calls)

    def test_exception_is_private(self):
        def fail(*args):raise RuntimeError('private-path-and-secret-details')
        self.server.runner=fail
        status,result=self.request()
        self.assertEqual(status,500)
        self.assertNotIn('private-path',json.dumps(result))
        self.assertFalse(self.server.generation_lock.locked())

    def test_invalid_output_rejected(self):
        self.server.runner=lambda *args:(b'not audio',wav(1))
        self.assertEqual(self.request()[0],400)

    def test_output_size_limit(self):
        with patch.object(worker,'MAX_OUTPUT',3):
            self.assertEqual(self.request()[0],400)


if __name__=='__main__':unittest.main()
