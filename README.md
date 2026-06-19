# Only Clipper

Only Clipper is an AI-powered video clipping system for turning long videos into short-form clips. It can ingest a local video file or a public video URL, run a staged processing pipeline, detect clip-worthy moments, render captioned exports, and provide dashboards for review, editing, QA, and download.

The project is designed to run locally for development, with Redis/RQ workers handling media processing in the background and FastAPI serving the pipeline API.

## What It Does

Only Clipper helps creators and teams:

- Upload a long-form video or paste a public video URL.
- Automatically process the source through a staged clipping pipeline.
- Generate short clips with platform-ready layouts.
- Apply karaoke-style captions and format presets.
- Review jobs, logs, progress, and failures from a dashboard.
- Browse rendered clips, preview them, archive/restore them, and download outputs.
- Edit clip metadata, transcript words, caption style, and export layout.
- QA clips using scoring, reasoning, analytics, and feedback signals.

## Current Capabilities

- Local video uploads and URL imports.
- Background pipeline using Redis and RQ.
- Groq and OpenAI-backed transcription/analysis workflows.
- Multi-stage job recovery and resume support.
- Export presets for vertical, square, and landscape formats.
- Multiple caption styles for short-form video.
- Local filesystem storage by default.
- Optional Supabase storage configuration.
- FastAPI REST API and generated API docs.
- Next.js frontend with upload, dashboard, clips, editor, and QA screens.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js, React, TypeScript |
| Backend | FastAPI, SQLAlchemy |
| Queue | Redis, RQ |
| Database | PostgreSQL by default, SQLite supported through `DATABASE_URL` |
| Media | FFmpeg, yt-dlp, OpenCV, MediaPipe |
| AI providers | Groq, OpenAI |
| Storage | Local filesystem, optional Supabase Storage |

## Repository Structure

```text
app/                 Next.js app routes and UI
api/                 FastAPI app, database setup, SQLAlchemy models
services/            Downloading, clipping, filtering, storage, FFmpeg, analysis helpers
workers/             Redis/RQ queue definitions and staged pipeline worker
alembic/             Database migration setup
scripts/             Utility scripts and migration helpers
storage/             Local runtime media output, ignored by git
temp/                Temporary runtime files, ignored by git
FUTURE.md            Product roadmap and future direction
```

## Prerequisites

Install these before running the app:

- Node.js 20 or newer
- Python 3.11 or newer
- Docker Desktop
- FFmpeg available on `PATH`
- A Groq API key, OpenAI API key, or both

Quick checks:

```powershell
node --version
python --version
docker --version
ffmpeg -version
```

## Quick Start

1. Install frontend dependencies:

```powershell
npm install
```

2. Create and activate a Python virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Create your local environment file:

```powershell
Copy-Item .env.example .env
```

4. Edit `.env` and add at least one AI provider key:

```env
GROQ_API_KEY=your_groq_key
OPENAI_API_KEY=your_openai_key
```

5. Start Redis and PostgreSQL:

```powershell
docker compose up -d redis postgres
```

6. Start the backend:

```powershell
.\venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

7. Start the worker in a second terminal:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

8. Start the frontend in a third terminal:

```powershell
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Local URL Rule

Use `127.0.0.1` for the backend instead of `localhost`.

The default `.env.example` uses:

```env
BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

This avoids Docker, WSL, and IPv6 conflicts where another app can answer `localhost:8000`.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Groq key for AI/transcription workflows. |
| `OPENAI_API_KEY` | OpenAI key for OpenAI workflows or fallback processing. |
| `REDIS_URL` | Redis connection string for RQ. |
| `ENVIRONMENT` | Runtime environment label. |
| `BASE_URL` | Backend base URL. |
| `DATABASE_URL` | SQLAlchemy database URL. |
| `STORAGE_BACKEND` | `local` or `supabase`. |
| `SUPABASE_URL` | Supabase project URL when using Supabase storage. |
| `SUPABASE_SERVICE_KEY` | Supabase service key. Do not expose publicly. |
| `SUPABASE_STORAGE_BUCKET` | Storage bucket name. |
| `NEXT_PUBLIC_API_URL` | Browser-visible backend URL. |
| `NEXT_PUBLIC_DEV_MODE` | Frontend development flag. |
| `AI_API_TIMEOUT_SECONDS` | AI request timeout. |
| `AI_API_MAX_RETRIES` | AI retry count. |
| `FFMPEG_TIMEOUT_SECONDS` | FFmpeg render timeout. |
| `FFPROBE_TIMEOUT_SECONDS` | FFprobe timeout. |
| `THUMBNAIL_TIMEOUT_SECONDS` | Thumbnail generation timeout. |
| `DEFAULT_DOWNLOAD_QUALITY` | `proxy` or `full`. |

Never commit `.env`. It is ignored because it contains secrets.

## Running The App

You need three long-running processes during development:

```powershell
# Terminal 1: backend API
.\venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2: queue worker
.\venv\Scripts\python.exe -m workers.run_worker

# Terminal 3: frontend
npm run dev
```

Redis and PostgreSQL should be running through Docker:

```powershell
docker compose up -d redis postgres
```

## User Workflow

1. Open the upload page.
2. Drop a video file or paste a public video URL.
3. Choose an export preset and caption style.
4. Launch the clipping pipeline.
5. Watch progress from the dashboard.
6. Open completed clips from the clips dashboard.
7. Review or adjust clips in the editor.
8. Use the QA screen to inspect scores, reasoning, and feedback.
9. Download finished clips from the clip library.

## Pipeline Overview

Jobs move through staged processing. The queue layer routes work to dedicated queues so slower stages do not block everything else.

Typical stages:

```text
job_created
metadata_fetched
download_started
download_completed
audio_extracted
transcription_completed
ai_analysis_completed
clips_generated
render_started
render_completed
export_completed
```

The worker entry point is:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

The main stage processor lives in:

```text
workers/pipeline_worker.py
```

## API Overview

Main endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/presets` | List export presets and caption styles. |
| `POST` | `/api/upload` | Create a job from a file or URL. |
| `GET` | `/api/jobs` | List jobs. |
| `GET` | `/api/status/{job_id}` | Read job status, progress, logs, and clips. |
| `POST` | `/api/job/{job_id}/resume` | Resume a stuck or queued job. |
| `GET` | `/api/metrics` | Read job and queue metrics. |
| `GET` | `/api/clips` | List rendered clips. |
| `GET` | `/api/clips/{clip_id}` | Read one clip. |
| `GET` | `/api/clips/{clip_id}/download` | Download one clip. |
| `POST` | `/api/clip/edit` | Edit and rerender a clip. |
| `GET` | `/api/qa/stats` | Read QA dashboard stats. |

FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

## Common Commands

Install frontend dependencies:

```powershell
npm install
```

Install backend dependencies:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start infrastructure:

```powershell
docker compose up -d redis postgres
```

Stop infrastructure:

```powershell
docker compose down
```

Run frontend:

```powershell
npm run dev
```

Build frontend:

```powershell
npm run build
```

Run backend:

```powershell
.\venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Run worker:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

## Database

The default example configuration uses PostgreSQL:

```env
DATABASE_URL=postgresql://clipper:clipper@localhost:5432/clipper
```

PostgreSQL is provided by `docker-compose.yml`. The app also supports SQLite by changing `DATABASE_URL`, for example:

```env
DATABASE_URL=sqlite:///storage/clipper.db
```

Alembic files are included under `alembic/`. During development the backend also calls `init_db()` on startup to ensure tables exist.

## Storage

Local storage is the default:

```env
STORAGE_BACKEND=local
```

Runtime media output is written under `storage/` and ignored by git.

For production-style storage, configure:

```env
STORAGE_BACKEND=supabase
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
SUPABASE_STORAGE_BUCKET=clips
```

## Git Hygiene

Ignored runtime and local files include:

- `.env`
- `*.log`
- `*.err.log`
- `.next/`
- `node_modules/`
- `venv/`
- `storage/`
- `temp/`
- `*.db`

Keep generated videos, local database files, logs, and secrets out of commits.

## Troubleshooting

### Upload says the server returned an error

Make sure the upload form is using the FastAPI backend directly:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

Large uploads should not be sent through the Next.js proxy.

### Jobs stay queued

Check Redis:

```powershell
docker exec onlyclipper-redis-1 redis-cli ping
```

Check the worker is running:

```powershell
.\venv\Scripts\python.exe -m workers.run_worker
```

### Frontend talks to the wrong backend

Use `127.0.0.1`, not `localhost`, for backend URLs.

### Backend starts but processing fails

Check:

- FFmpeg is installed and on `PATH`.
- At least one AI key is set.
- Redis is running.
- The worker is running.
- `storage/` and `temp/` are writable.

## For New Developers

Before making changes:

1. Run the app locally end to end.
2. Create a small test job from a short video or public test URL.
3. Watch the job move through the dashboard.
4. Inspect backend logs and worker logs while the job runs.
5. Keep changes scoped and avoid committing generated runtime files.

Recommended checks before pushing:

```powershell
npm run build
python -m compileall api services workers scripts
```

If a check fails because of unrelated local state, document it in your PR or commit notes.

## Roadmap

See [FUTURE.md](./FUTURE.md) for the product roadmap and planned pipeline expansions.

## Contributing

This repository is currently moving quickly. Keep contributions practical:

- Prefer small, focused commits.
- Keep secrets out of git.
- Add or update documentation when setup or workflow changes.
- Preserve the staged pipeline model unless there is a clear reason to change it.
- Test upload, job status, worker processing, and clip browsing after backend changes.

## License

No license has been added yet. Add one before distributing the project or accepting external contributions.
