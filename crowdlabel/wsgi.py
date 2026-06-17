"""WSGI entry point for the CrowdLabel prototype."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "crowdlabel.settings")

application = get_wsgi_application()
