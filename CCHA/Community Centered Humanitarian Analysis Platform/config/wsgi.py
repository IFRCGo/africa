"""WSGI entry point: the handle that gunicorn grabs to run this Django site.

gunicorn (see the Dockerfile) imports the "application" object below and hands
every incoming HTTP request to it.
"""
import os

from django.core.wsgi import get_wsgi_application

# Tell Django which settings module to load before anything else happens.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
