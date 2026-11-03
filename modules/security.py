
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.shortcuts import redirect


# Actions that require explicit consent.

CONSENT_SESSION_KEY = "voice_cloner_consent_acknowledged"
AUDIO_ACTIONS = {
    "upload",
    "normalize",
    "generate",
}


class MaxAudioSizeUploadHandler(FileUploadHandler):
    """
    Reject audio files exceeding the configured size limit.

    This handler operates while Django receives the upload,
    rather than waiting until the view saves the file.
    """

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_size = 0

    def receive_data_chunk(self, raw_data, start):

        self.file_size += len(raw_data)

        if self.file_size > settings.MAX_AUDIO_UPLOAD_BYTES:

            self.request._audio_upload_too_large = True

            raise StopUpload(connection_reset=False)

        return raw_data

    def file_complete(self, file_size):
        return None



def consent_required(view):
    """
    Require explicit consent before audio upload or processing.

    Consent is remembered for the current authenticated session.
    Unchecking the checkbox withdraws consent.
    Clear All remains accessible without consent.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):

        if request.method != "POST":
            return view(request, *args, **kwargs)

        post = request.POST
        action = post.get("action", "")

        if action in AUDIO_ACTIONS:

            _ = request.FILES

            if getattr(
                request,
                "_audio_upload_too_large",
                False
            ):
                messages.error(
                    request,
                    "The uploaded audio exceeds the 25 MB limit."
                )
                return redirect("voice_cloner_home")

            field = settings.VOICE_CLONING_CONSENT_FIELD

            accepted = post.get(field, "").strip().lower()

            accepted_values = {
                "1",
                "true",
                "yes",
                "on",
                "accepted",
            }

            if accepted in accepted_values:

                # Remember consent for subsequent requests.
                request.session[CONSENT_SESSION_KEY] = True

            else:

                # Missing checkbox means consent was withdrawn
                # or was never provided.
                request.session.pop(
                    CONSENT_SESSION_KEY,
                    None
                )

                messages.error(
                    request,
                    "Please confirm that you have permission "
                    "to use the uploaded voice before continuing."
                )

                return redirect("voice_cloner_home")

        return view(request, *args, **kwargs)

    return wrapper