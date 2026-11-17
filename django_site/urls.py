from django.contrib import admin
from django.urls import include, path

from modules.auth_views import register


urlpatterns = [
    # Registration
    path(
        "accounts/register/",
        register,
        name="register"
    ),

    # Django login, logout, and password management
    path(
        "accounts/",
        include("django.contrib.auth.urls")
    ),

    path("admin/", admin.site.urls),

    # Voice Cloner application
    path("", include("modules.urls")),
]