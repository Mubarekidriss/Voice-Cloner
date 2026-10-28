from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="voice_cloner_home"),
    path("audio/<str:kind>/", views.audio_file, name="voice_cloner_audio"),
]
