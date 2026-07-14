FROM python:3.12.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The agenda picture is drawn with Pillow, and slim ships no fonts at all:
# without DejaVu there is nothing to render Cyrillic with.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY notifier /app/notifier

# Healthy = the update loop refreshed data from Exchange recently.
# HEALTH_MAX_AGE (seconds) should be a few times UPDATE_INTERVAL.
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import os,sys,time; p=os.environ.get('HEALTH_FILE','/tmp/notifier-healthy'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < int(os.environ.get('HEALTH_MAX_AGE','600')) else 1)"]

CMD ["python", "-m", "notifier"]
