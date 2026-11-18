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

# PyTorch first, from its CPU-only index. docling and easyocr both sit on
# torch, and the default PyPI wheel drags in the CUDA runtime - about 2GB of
# GPU libraries this container can never use. The versions are pinned HERE AND
# IN requirements.txt to the same values on purpose: without the pin, the
# resolve below is free to decide something wants a different torch and
# replace these wheels with the CUDA ones, silently undoing the whole layer.
RUN pip install --no-cache-dir \
    torch==2.6.0 torchvision==0.21.0 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt /app/requirements.txt

# rapidocr - a docling dependency this project never calls - requires
# opencv-python, the GUI build. easyocr requires opencv-python-headless. Both
# distributions install the SAME cv2/ directory and the GUI build wins, so
# every "import cv2" in the image lands on a wheel linked against libxcb.so.1
# and libGL, neither of which python:3.11-slim carries. That breaks far more
# than rapidocr: "import easyocr" raises it too, and the model download below
# dies at its RapidOCR stage AFTER seventeen minutes of successful downloads.
#
# The reinstall is not belt-and-braces. The two distributions share cv2/, so
# uninstalling opencv-python deletes the directory headless is also recorded
# as owning and leaves ModuleNotFoundError in its place. The version is read
# back rather than pinned here so there is no second place to update when the
# resolve moves. All of it rides in the requirements layer on purpose: a later
# RUN would delete the GUI wheel without shrinking the image, since the bytes
# stay in the layer underneath.
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && V=$(pip show opencv-python-headless | awk '/^Version:/{print $2}') \
 && pip uninstall -y opencv-python \
 && pip install --no-cache-dir --force-reinstall --no-deps "opencv-python-headless==$V"

# Bake the model weights into the image. Without this, the FIRST click on
# "Read these documents" downloads them inside a detached subprocess with no
# progress anywhere a person can see it, and fails outright on a machine with
# no internet.
#
# -o is what puts them where DOCLING_ARTIFACTS_PATH says. Overriding HOME
# instead would put them in $HOME/.cache/docling/models - a DIFFERENT
# directory - and the build would still succeed, leaving artifacts_path
# pointing at an empty folder and every conversion failing at run time with a
# missing layout model.
ENV DOCLING_ARTIFACTS_PATH=/opt/docling/models
RUN mkdir -p /opt/docling/models \
    && docling-tools models download -o /opt/docling/models

# EasyOCR fetches its own detection and recognition weights, which
# docling-tools does not cover. Instantiating a Reader is what pulls them.
#
# TWO READERS, NOT ONE, AND THIS IS NOT A CHOICE. EasyOCR refuses to load
# Arabic beside any other non-English language:
#   ValueError: Arabic is only compatible with English
# So no single language list covers an Arabic report and a French one, and
# Docling takes exactly one ocr_options. Both model sets are baked here
# anyway - the weights are small next to torch, and it means switching
# DOCLING_OCR_LANGS between scripts is a .env edit and a restart rather than
# a rebuild.
RUN python -c "import easyocr; easyocr.Reader(['en','ar'], gpu=False, \
    model_storage_directory='/opt/docling/models', download_enabled=True)" \
 && python -c "import easyocr; easyocr.Reader(['en','fr'], gpu=False, \
    model_storage_directory='/opt/docling/models', download_enabled=True)"

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
