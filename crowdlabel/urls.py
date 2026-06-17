"""Project URL configuration. All routes live in the core app."""
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
]
