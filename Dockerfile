FROM python:3.11-slim

# ffmpeg for burning captions, fonts for the ASS renderer (libass).
# DejaVu Sans Bold stands in for Arial Black, which is not on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Whisper model into the image so the first real user request
# does not have to wait for a ~140 MB download.
ARG WHISPER_MODEL=tiny
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"

COPY app ./app
COPY static ./static

# The model is already baked into the image above; loading it offline at
# runtime avoids slow/hanging HuggingFace update checks on every start.
ENV HF_HUB_OFFLINE=1

ENV JOBS_DIR=/tmp/caption-jobs
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
