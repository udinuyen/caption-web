#!/usr/bin/env python3
"""Web nhận video -> tạo phụ đề tự động (Whisper) -> burn vào video.

One FastAPI service serves both the API and the static upload page, so a
single Render service is all you need. Jobs run one at a time on CPU
(a lock queues the rest) and finished files are kept for 1 hour.
"""
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .caption import (build_ass_sentence, build_ass_word, burn, probe,
                      transcribe)

BASE = Path(__file__).resolve().parent.parent
JOBS_DIR = Path(os.environ.get("JOBS_DIR", "/tmp/caption-jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "300"))
JOB_TTL_SECONDS = 3600
ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}

app = FastAPI(title="Auto Caption Web")
JOBS: dict = {}
LOCK = threading.Lock()          # one transcription at a time (CPU)
RUNNING = threading.Semaphore(1)


def cleanup_old_jobs():
    now = time.time()
    for job_id, job in list(JOBS.items()):
        if now - job["created"] > JOB_TTL_SECONDS:
            shutil.rmtree(job["dir"], ignore_errors=True)
            JOBS.pop(job_id, None)


def run_job(job_id: str):
    job = JOBS[job_id]
    with RUNNING:
        job["status"] = "processing"
        try:
            job["step"] = "Đang nghe và chép lời (Whisper)..."
            segments, detected = transcribe(job["input"], MODEL_NAME,
                                            job["language"])
            job["detected_language"] = detected

            src_w, src_h, _ = probe(job["input"])
            if job["to_916"]:
                play_w, play_h = 1080, 1920
            else:
                play_w, play_h = src_w, src_h

            job["step"] = "Đang tạo file phụ đề..."
            ass_path = job["dir"] / "captions.ass"
            if job["style"] == "word":
                build_ass_word(segments, ass_path, play_w, play_h)
            else:
                build_ass_sentence(segments, ass_path, play_w, play_h)

            job["step"] = "Đang gắn phụ đề vào video (FFmpeg)..."
            out_path = job["dir"] / "video-phu-de.mp4"
            burn(job["input"], ass_path, out_path, job["to_916"],
                 job["boost_audio"], src_w, src_h)

            job["output"] = out_path
            job["ass"] = ass_path
            job["srt"] = ass_path.with_suffix(".srt")
            job["status"] = "done"
            job["step"] = "Xong!"
        except Exception as exc:  # surface the real reason to the page
            job["status"] = "error"
            job["step"] = str(exc)[:600]


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL_NAME}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    style: str = Form("sentence"),
    to_916: bool = Form(False),
    boost_audio: bool = Form(False),
):
    cleanup_old_jobs()
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Chỉ nhận các định dạng: "
                                 f"{', '.join(sorted(ALLOWED_EXT))}")
    if style not in ("sentence", "word"):
        raise HTTPException(400, "style phải là 'sentence' hoặc 'word'")
    if language not in ("auto", "en", "vi"):
        raise HTTPException(400, "language phải là auto, en hoặc vi")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    input_path = job_dir / f"input{ext}"
    size = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    with input_path.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(400, f"File quá lớn "
                                         f"(tối đa {MAX_UPLOAD_MB} MB)")
            fh.write(chunk)
    if size == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, "File rỗng")

    JOBS[job_id] = {
        "id": job_id, "created": time.time(), "status": "queued",
        "step": "Đang chờ tới lượt...", "dir": job_dir,
        "input": input_path, "language": language, "style": style,
        "to_916": to_916, "boost_audio": boost_audio,
        "output": None, "ass": None, "srt": None,
        "detected_language": None,
    }
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Không thấy job (có thể đã quá 1 giờ, "
                                 "file đã bị xóa)")
    data = {"status": job["status"], "step": job["step"],
            "detected_language": job["detected_language"]}
    if job["status"] == "done":
        data["downloads"] = {
            "video": f"/api/jobs/{job_id}/download/video",
            "ass": f"/api/jobs/{job_id}/download/ass",
            "srt": f"/api/jobs/{job_id}/download/srt",
        }
    return JSONResponse(data)


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404, "Chưa có file để tải")
    mapping = {"video": (job["output"], "video-phu-de.mp4", "video/mp4"),
               "ass": (job["ass"], "captions.ass", "text/plain"),
               "srt": (job["srt"], "captions.srt", "text/plain")}
    if kind not in mapping:
        raise HTTPException(404, "Loại file không đúng")
    path, name, media = mapping[kind]
    if not path or not path.exists():
        raise HTTPException(404, "File đã bị xóa")
    return FileResponse(path, filename=name, media_type=media)


# Static upload page, mounted last so /api wins.
app.mount("/", StaticFiles(directory=BASE / "static", html=True),
          name="static")
