# FP11 website connection, review build

Prepared November 21, 2026 against deployed branch commit de278d2. This patch has NOT been pushed or deployed. It adds the website connection as well as the loopback worker. Main is untouched. There is no public tunnel and no paid service.

## What was actually verified

- Existing suite: 95 tests and 26 subtests pass, including 17 worker tests.
- Django integration: 15 tests pass against an actual local HTTP worker with a simulated engine. Run `python manage.py test modules.web_tests -v 2` in a Python 3.11 web environment.
- Local Chromium browser: signed-in upload, consent, normalize, Generate, both audio players, both byte-exact downloads and Clear all work. The audio is synthetic test tones, NOT speech or a real cloned voice.
- The web-only Python environment starts without torch, TTS or pydub loaded, and without setting the model-license acceptance flag. FFmpeg initializes only when conversion needs it.
- Negative checks cover login/CSRF/consent, bad key, busy worker, invalid input/output, timeouts, oversized responses, stale output removal, browser-session isolation and inactive-folder cleanup. Some malformed-response/timeout checks use injected responses, not an external failing network.

These results do NOT prove real XTTS generation, voice quality, Render operation, public tunnel operation, native Windows/Mac operation or free-tier memory consumption. There is no live model host yet.

## Changed pieces

- `local_worker.py`: loopback-only authenticated HTTP worker.
- `modules/remote_worker.py`: bounded Django client, HTTPS origin validation, no redirects/proxies, output WAV checks and private errors.
- `modules/views.py`: remote/local selection, conversion before remote generation, failed-retry cleanup and 2000-character limit.
- `modules/apps.py`: removed eager FFmpeg initialization and automatic model-terms acceptance.
- `django_site/settings.py`: environment-based remote settings.
- `requirements-web.txt` and `build-web.sh`: web-only build without model dependencies. Existing full model requirements/build are preserved.
- `templates/index.html` and `RESPONSIBLE_USE.md`: truthful remote processing/retention wording.
- `tests/test_local_worker.py` and `modules/web_tests.py`: worker and website checks.

## Local synthetic connection check

Use Python 3.11 and install `requirements-web.txt` plus pytest. The Django test command creates its own temporary database, synthetic sample and loopback worker. It does not download XTTS or open a tunnel. Run existing core tests separately with `python -m pytest -q`; Django web tests use the explicit command above and do not change the core test runner.

## Real model host, still to be agreed and tested

Mikita's computer is a proposed host, not an accepted commitment. The host must review the actual model terms before any download/use. Install the existing platform-specific model environment, review the worker patch, and privately configure `WORKER_SECRET_KEY` using a new random printable ASCII secret of at least 32 characters. Never use the public test placeholder or send a real secret in chat/source/screenshots. Then run:

    python local_worker.py --device auto --port 8001

It binds only to 127.0.0.1. No tunnel is created. The worker imports the existing model helper only for an authenticated, validated generation request. A real permitted voice sample is still required to verify both standard and cloned speech. Sample-owner consent must include transfer to the chosen model host.

## Website configuration, after patch review and deployment approval

Configure these privately on the website host:

- `VOICE_INFERENCE_MODE=remote`
- `VOICE_WORKER_URL`: the approved tunnel HTTPS origin only, with no path/query/user info.
- `VOICE_WORKER_SECRET`: the same private key as the worker.
- `VOICE_WORKER_TIMEOUT=180`: configurable 1 to 600 seconds. Align the web-server request timeout with the chosen value. A web timeout does not cancel the model computation.

Use `bash build-web.sh` as the web build command. That command is an additional selectable path, NOT an applied Render configuration change. Keep the existing production secret, allowed hosts, HTTPS and database settings. Do not replace existing account/database settings blindly. `VOICE_WORKER_ALLOW_LOOPBACK=true` is only for local debug testing and is disabled by production settings. Remote mode never falls back to loading the model in the web process.

Public tunnel setup, secret collection and Render-account edits still need approval and a real host. Cloudflare's official Quick Tunnel docs describe a temporary development URL with no account/domain requirement, no uptime guarantee, and a new hostname after each restart. Its published-application proxy layer documents a 125-second read timeout; a slow cold model call may need asynchronous jobs/polling rather than a larger Django timeout alone. These are documented limits, not a successful live tunnel test. This patch does not create accounts or promise a permanent URL. Official references checked November 21: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ , https://developers.cloudflare.com/tunnel/downloads/ , https://developers.cloudflare.com/fundamentals/reference/connection-limits/ .

## Operating limits and final demo gate

One generation at a time; busy work fails rather than queueing samples. Input is limited to 25 MiB, 6 to 30 seconds, with text limited to 2000 characters. Model generation has no hard deadline/cancellation and reloads through the helper each request, so first runs can be slow. Client disconnects do not cancel work. Worker temp deletion is best-effort; crashes can leave files. Website inactive-folder cleanup runs on later access, not on a timer; restart storage loss is possible. Database expiry remains unverified.

Before claiming completion: approve/publish the patch, choose and authorize the host/tunnel, review model terms, run real baseline and cloned speech, then test the deployed website from another device for login, consent, upload/normalization, generation, audible comparison, both downloads, Clear all, bad/busy/offline-worker failures and restart behavior. Record measured results, not assumptions. Final signoff and D2L are untouched.
