"""ASGI entry point - the async equivalent of wsgi.py.

Not used by the default Docker setup (gunicorn uses WSGI), but Django expects
this file to exist and it makes future async work possible.
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
