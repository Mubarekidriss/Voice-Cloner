# Responsible use and audio handling

This is ICS 499 coursework. This document describes the FP11 review patch, not proof that the deployed service has been updated.

## Permission and acceptable use

Clone only your own voice or a voice whose owner gave clear permission. Do not impersonate, deceive, defraud, harass or harm anyone. Use text you have permission to reproduce. The website requires login and checks consent server-side on every upload, normalize and generate request, with Django CSRF protection. In remote mode, permission must also cover sending the sample and text to the configured model computer. Only use a host you trust.

## Where processing happens

In local mode, model processing happens on the computer running the app. In remote mode, the browser uploads to the website, the website sends the normalized sample and text over its configured connection to the model worker, and the worker returns baseline and cloned audio. Both outputs use XTTS, with its configured default speaker for the baseline. This is not on-device browser inference. The model computer must be running and reachable. Colab notebooks remain separate: their data is processed in Google's runtime.

## Storage and deletion

The website stores uploads, normalized WAV and generated audio in private user/browser-session folders under PRIVATE_AUDIO_ROOT, outside MEDIA_ROOT. Audio routes require login and the matching session, with no-store headers. Clear all deletes that session folder. Replacing a reference invalidates older derived audio. A new generation removes earlier outputs before trying again so a failed retry does not display stale results.

Inactive website folders older than one hour are cleaned when the app is accessed again, not by a guaranteed deletion timer. Host restarts may remove files sooner. This policy concerns audio folders, not account/database deletion. Database expiry is not verified.

The worker processes one generation at a time. Its temporary input and output files are removed after success or failure on a best-effort basis. Crashes or power loss can leave temporary files. Clear all on the website does not cancel a running worker request or guarantee secure erasure on either host. Model computation may continue after a timeout/disconnect.

## Connection safeguards and limits

The worker binds to loopback and needs a private shared key; browsers do not receive that key. Public exposure requires a separately reviewed secure connection. The website client requires HTTPS outside explicitly allowed local debug tests, does not follow redirects or inherit proxies, and validates bounded JSON/WAV responses before saving them. The worker rejects browser-origin requests. These are safeguards, not a production-security certification.

Samples are limited to 25 MiB and 6 to 30 seconds. Text is limited to 2000 characters. Both generated WAV outputs are size-limited and validated. Logs must not include voice data, input text or shared keys. Keep production DEBUG disabled and use a private production Django secret, allowed hosts and HTTPS configuration.

## Model terms and output risks

Review the model publisher's current terms before downloading or using XTTS. The existing project references the Coqui Public Model License at https://coqui.ai/cpml. The FP11 Django startup and worker do not automatically set a license-acceptance environment variable. This document is not acceptance of terms and does not establish rights for any particular use.

Cloned speech can be mistaken for a real person's voice. Quality varies. Do not present an output as evidence of what someone actually said. Keep samples and outputs private and delete files you no longer need.
