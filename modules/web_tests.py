"""Real Django flow to real loopback HTTP worker, fake speech engine only.
Run: python manage.py test modules.web_tests -v 2
"""
import array
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import wave
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from local_worker import WorkerServer
from modules.remote_worker import RemoteService, RemoteWorkerError

TOKEN = 'test-only-placeholder-not-a-real-secret'

def wav(seconds=7, level=2000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(array.array('h', [level, -level] * (8000*seconds//2)).tobytes())
    return output.getvalue()

class RemoteWebTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.calls = []
        def fake(text, language, audio, device):
            self.calls.append((text, language))
            return wav(1,1000), wav(2,3000)
        self.server = WorkerServer(('127.0.0.1',0),TOKEN,runner=fake)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.override = override_settings(VOICE_INFERENCE_MODE='remote',VOICE_WORKER_URL=f'http://127.0.0.1:{self.server.server_port}',
            VOICE_WORKER_SECRET=TOKEN,VOICE_WORKER_ALLOW_LOOPBACK=True,VOICE_WORKER_TIMEOUT=2,
            PRIVATE_AUDIO_ROOT=Path(self.folder.name)/'private', MEDIA_ROOT=Path(self.folder.name)/'media')
        self.override.enable()
        self.user = get_user_model().objects.create_user(username='synthetic-test')
        self.user.set_unusable_password(); self.user.save()
        self.client.force_login(self.user)

    def tearDown(self):
        self.override.disable(); self.server.shutdown(); self.server.server_close(); self.thread.join(); self.folder.cleanup()

    def post(self, action, **extra):
        data = dict(action=action,consent_ack='yes',text_input='Both outputs use this sentence.',language='English')
        data.update(extra)
        return self.client.post('/',data,follow=True)

    def upload(self):
        return self.post('upload',reference_audio=SimpleUploadedFile('synthetic.wav',wav(),content_type='audio/wav'))

    def assert_missing_outputs(self):
        self.assertEqual(self.client.get('/audio/baseline/').status_code,404)
        self.assertEqual(self.client.get('/audio/cloned/').status_code,404)

    def test_upload_normalize_generate_playback_download_clear(self):
        self.assertContains(self.upload(),'Voice sample saved')
        self.assertContains(self.post('normalize'),'Audio normalized successfully')
        self.assertContains(self.post('generate'),'Speech generated')
        self.assertEqual(self.calls,[('Both outputs use this sentence.','English')])
        for name, expected in [('baseline',wav(1,1000)),('cloned',wav(2,3000))]:
            response=self.client.get(f'/audio/{name}/')
            self.assertEqual(response.status_code,200)
            self.assertEqual(b''.join(response.streaming_content),expected)
            self.assertIn('no-store',response['Cache-Control'])
            response.close()
            response=self.client.get(f'/audio/{name}/?download=1')
            self.assertIn('attachment',response['Content-Disposition']);response.close()
        other=Client();other.force_login(self.user)
        self.assertEqual(other.get('/audio/baseline/').status_code,404)
        self.post('clear')
        self.assert_missing_outputs()
        self.assertFalse(list((Path(self.folder.name)/'private'/'sessions').iterdir()))

    def test_generate_without_separate_normalize(self):
        self.upload()
        self.assertContains(self.post('generate'),'Speech generated')
        self.assertEqual(len(self.calls),1)

    def test_auth_and_per_request_consent(self):
        self.client.logout()
        self.assertEqual(self.client.get('/').status_code,302)
        self.client.force_login(self.user)
        self.assertContains(self.post('upload',consent_ack='',reference_audio=SimpleUploadedFile('sample.wav',wav())), 'Please confirm')
        self.upload()
        self.assertContains(self.post('generate',consent_ack=''),'Please confirm')
        self.assertFalse(self.calls)

    def test_wrong_worker_key_and_busy(self):
        self.upload()
        with override_settings(VOICE_WORKER_SECRET='incorrect-test-placeholder-secret-value'):
            self.assertContains(self.post('generate'),'Worker key was rejected')
        self.server.generation_lock.acquire()
        try:self.assertContains(self.post('generate'),'model computer is busy')
        finally:self.server.generation_lock.release()
        self.assert_missing_outputs()

    def test_invalid_response_and_no_partial_outputs(self):
        self.upload()
        self.server.runner=lambda *args:(b'bad',wav(1))
        self.assertContains(self.post('generate'),'worker rejected',status_code=200)
        self.assert_missing_outputs()

    def test_failed_retry_removes_stale_outputs(self):
        self.upload();self.post('generate')
        self.assertContains(self.post('generate',text_input='x'*2001),'2000 characters')
        self.assert_missing_outputs()

    def test_expired_workspace_cleanup(self):
        self.upload()
        session=self.client.session
        path=Path(self.folder.name)/'private'/'sessions'/session['voice_cloner_workspace']
        os.utime(path,(1,1))
        self.client.get('/')
        self.assertFalse(path.exists())

    def test_endpoint_rules_and_no_redirect(self):
        reference=Path(self.folder.name)/'sample.wav';reference.write_bytes(wav())
        for url in ['http://example.invalid','https://user:pass@example.invalid','https://example.invalid/?x=1','file:///tmp/test']:
            with self.subTest(url=url),override_settings(VOICE_WORKER_URL=url),self.assertRaises(RemoteWorkerError):
                RemoteService().generate_voices('hi',reference,'English')
        with override_settings(VOICE_WORKER_ALLOW_LOOPBACK=False),self.assertRaises(RemoteWorkerError):
            RemoteService().generate_voices('hi',reference,'English')

    def test_worker_failure_is_private(self):
        self.upload()
        def fail(*args):raise RuntimeError('private filesystem detail')
        self.server.runner=fail
        response=self.post('generate')
        self.assertContains(response,'Worker could not generate')
        self.assertNotContains(response,'private filesystem detail')
        self.assert_missing_outputs()

    def test_csrf_missing_rejected(self):
        browser=Client(enforce_csrf_checks=True);browser.force_login(self.user)
        self.assertEqual(browser.post('/',{'action':'generate','consent_ack':'yes'}).status_code,403)
        self.assertFalse(self.calls)

    def test_corrupt_upload_rejected(self):
        self.assertContains(self.post('upload', reference_audio=SimpleUploadedFile('bad.wav',b'bad audio')),'could not be used')
        self.assertFalse(self.calls)

    def test_client_rejects_malformed_and_oversized_responses(self):
        from email.message import Message
        from unittest.mock import MagicMock
        reference=Path(self.folder.name)/'sample.wav';reference.write_bytes(wav())
        headers=Message();headers['Content-Type']='application/json'
        for data in [b'not json',b'{}',json.dumps({'baseline_wav_base64':'!!!','clone_wav_base64':'!!!'}).encode()]:
            response=MagicMock();response.status=200;response.headers=headers;response.read.return_value=data
            with patch('modules.remote_worker.build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value=response
                with self.assertRaises(RemoteWorkerError):RemoteService().generate_voices('hi',reference,'English')
        response.read.return_value=b'x'*11
        with patch('modules.remote_worker.MAX_RESPONSE',10),patch('modules.remote_worker.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=response
            with self.assertRaises(RemoteWorkerError):RemoteService().generate_voices('hi',reference,'English')

    def test_timeout_has_safe_message(self):
        self.upload()
        with patch('modules.remote_worker.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError('private details')
            response=self.post('generate')
        self.assertContains(response,'unavailable or timed out')
        self.assertNotContains(response,'private details')
        self.assert_missing_outputs()

    def test_no_redirect_callback(self):
        from modules.remote_worker import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_real_redirect_is_not_followed(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        calls=[]
        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                calls.append(self.path)
                self.send_response(302);self.send_header('Location','/leak');self.end_headers()
            def do_GET(self):
                calls.append(self.path);self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),RedirectHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        reference=Path(self.folder.name)/'sample.wav';reference.write_bytes(wav())
        try:
            with override_settings(VOICE_WORKER_URL=f'http://127.0.0.1:{server.server_port}'),self.assertRaises(RemoteWorkerError):
                RemoteService().generate_voices('hi',reference,'English')
            self.assertEqual(calls,['/generate'])
        finally:server.shutdown();server.server_close();thread.join()
