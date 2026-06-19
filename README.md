# Only Clipper

Only Clipper is a local-first AI video clipping app. It ingests a video file or public video URL, runs a staged processing pipeline, finds short-form clip candidates, renders captioned exports, and exposes dashboards for reviewing, editing, downloading, and quality-checking clips.

## Features

- Upload local video files or import public video URLs.
- Staged background pipeline with Redis/RQ workers.
- AI transcription and clip analysis through Groq or OpenAI.
- Captioned exports for TikTok/Reels, YouTube Shorts, square, and landscape layouts.
- Multiple karaoke caption styles.
- Project dashboard with live status, progress, retry/resume controls, and logs.
- Clip library with filtering, preview, archive/restore, download, and feedback events.
- Editor for updating clip metadata, transcript words, caption style, and layout.
- QA dashboard for reviewing clip scores, reasoning, analytics, and feedback.
- Local filesystem storage by default, with Supabase storage support configured for production.

## Tech Stack

- Frontend: Next.js, React, TypeScript
- Backend: FastAPI, SQLAlchemy
- Queue: Redis, RQ
- Database: PostgreSQL for production-style local development, SQLite also supported by `DATABASE_URL`
- Media: FFmpeg, yt-dlp, OpenCV, MediaPipe
- AI: Groq and OpenAI APIs

## Prerequisites

- Node.js 20+
- Python 3.11+
- Docker Desktop
- FFmpeg available on `PATH`
- A Groq API key, OpenAI API key, or both

## Local Setup

1. Install JavaScript dependencies:

```powershell
npm install
```

2. Create and activate a Python virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Create your environment file:

```powershell
Copy-Item .env.example .env
```

4. Edit `.env` and set at least one AI provider key:

```env
GROQ_API_KEY=...
OPENAI_API_KEY=...
```

5. Start Redis and PostgreSQL:

```powershell
docker compose up -d redis postgres
```

6. Start the FastAPI backend:

```powershell
.\venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

7. Start the RQ worker in a second terminal:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

8. Start the Next.js frontend in a third terminal:

```powershell
npm run dev
```

Open the app at:

```text
http://127.0.0.1:3000
```

The backend docs are available at:

```text
http://127.0.0.1:8000/docs
```

## Important Local URL Note

The default local config uses `127.0.0.1` instead of `localhost` for the backend:

```env
BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

This avoids conflicts where Docker, WSL, or another local app answers `localhost:8000` on IPv6.

## Environment Variables

Key variables from `.env.example`:

- `GROQ_API_KEY`: Groq API key for transcription/analysis workflows.
- `OPENAI_API_KEY`: OpenAI API key for fallback or OpenAI-based processing.
- `REDIS_URL`: Redis connection string for RQ queues.
- `DATABASE_URL`: SQLAlchemy database URL.
- `STORAGE_BACKEND`: `local` or `supabase`.
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_STORAGE_BUCKET`: Supabase storage settings.
- `NEXT_PUBLIC_API_URL`: Browser-visible FastAPI backend URL.
- `DEFAULT_DOWNLOAD_QUALITY`: `proxy` or `full`.
- Timeout variables for AI, FFmpeg, FFprobe, and thumbnails.

Do not commit `.env`; it is ignored because it contains secrets.

## Common Commands

Run the frontend:

```powershell
npm run dev
```

Build the frontend:

```powershell
npm run build
```

Run the backend:

```powershell
.\venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Run the worker:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

Start infrastructure:

```powershell
docker compose up -d redis postgres
```

Stop infrastructure:

```powershell
docker compose down
```

## API Overview

Main backend endpoints:

- `GET /api/presets`: available export presets and caption styles.
- `POST /api/upload`: create a video job from a local file or URL.
- `GET /api/jobs`: list processing jobs.
- `GET /api/status/{job_id}`: get status, progress, logs, and clips for a job.
- `POST /api/job/{job_id}/resume`: resume a stuck or queued job.
- `GET /api/metrics`: job and queue metrics.
- `GET /api/clips`: list rendered clips.
- `POST /api/clip/edit`: update and rerender a clip.
- `GET /api/qa/stats`: QA dashboard summary.

## Project Structure

```text
app/                 Next.js app routes and UI
api/                 FastAPI app, database setup, SQLAlchemy models
services/            Downloading, clipping, filtering, storage, FFmpeg, analysis helpers
workers/             Redis/RQ queue and staged pipeline worker
alembic/             Database migration setup
scripts/             Utility and migration scripts
storage/             Local runtime media output, ignored by git
temp/                Temporary runtime files, ignored by git
```

## Runtime Data

The following are intentionally ignored:

- `.env`
- `*.log`
- `*.err.log`
- `.next/`
- `node_modules/`
- `venv/`
- `storage/`
- `temp/`
- `*.db`

## Troubleshooting

If uploads fail with a server error, confirm the browser is using `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`. Large uploads should post directly to FastAPI, not through the Next.js proxy.

If jobs stay queued, confirm Redis is running and the worker is active:

```powershell
docker exec onlyclipper-redis-1 redis-cli ping
.\venv\Scripts\python.exe -m workers.run_worker
```

If the dashboard talks to the wrong backend, avoid `localhost` and use `127.0.0.1` for both frontend and backend URLs.

## License

No license has been added yet. Add one before distributing or accepting external contributions.
