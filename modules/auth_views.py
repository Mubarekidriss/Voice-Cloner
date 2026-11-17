from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .forms import RegistrationForm


@require_http_methods(["GET", "POST"])
def register(request):
    """Register a new user and sign them in."""

    # Users who are already signed in don't need to register again.
    if request.user.is_authenticated:
        return redirect("voice_cloner_home")

    next_url = (
        request.POST.get("next", "")
        if request.method == "POST"
        else request.GET.get("next", "")
    )

    if request.method == "POST":

        form = RegistrationForm(request.POST)

        if form.is_valid():

            user = form.save()

            # Authenticate the new user immediately.
            login(request, user)

            messages.success(
                request,
                "Your account was created successfully. Welcome!"
            )

            # Only redirect to a safe URL on this same website.
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)

            return redirect("voice_cloner_home")

    else:

        form = RegistrationForm()

    return render(
        request,
        "registration/register.html",
        {
            "form": form,
            "next": next_url,
        }
    )