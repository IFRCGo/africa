# ---------------------------------------------------------------------------
# The image that runs Django (the dashboard, the updater, the admin and the
# pipeline). Built by docker-compose as the "web" service.
# ---------------------------------------------------------------------------

# Start from the official slim Python image: small, and Python is ready to use.
FROM python:3.11-slim

# Keep Python from writing .pyc files and make its output appear immediately
# in "docker compose logs" (important for the updater's live progress bar).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install the packages first, on their own layer. Docker caches this step, so
# editing the code later rebuilds in seconds instead of minutes.
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Now copy the project itself.
COPY . /app

# The entrypoint waits for PostgreSQL, applies migrations, then starts the server.
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]

# gunicorn is the web server. Threads (not just processes) matter here: the
# updater holds one connection open for the whole length of a pipeline run, and
# a single-threaded worker would block every other request while it does.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "0", \
     "--access-logfile", "-"]
