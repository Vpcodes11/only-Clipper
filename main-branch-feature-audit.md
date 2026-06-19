# Main Branch → Current Branch Feature Extraction Audit

## Executive Summary

The main branch (`origin/main`) is a **different backend architecture** (app/ core modules, Celery workers) vs. the current branch's RQ-based pipeline (services/ + workers/). The current branch has a **vastly superior pipeline architecture** — staged RQ queues, idempotent stages, cross-model judging, pre-LLM signals, rule filters, and psychology scoring. The main branch is an older codebase with different conventions.

**Verdict: The main branch contains ~5 files worth porting as isolated utilities.** The rest is either duplicated (worse version), conflicting architecture, or dead features. DO NOT port most of it.

---

## Section A: SAFE QUICK WINS (Low Risk, High Value)

### Feature 1: Content Safety Moderation
**Source:** `app/core/moderation.py` (origin/main)
**Status:** NOT present in current branch

#### Why It Matters
Prevents the pipeline from generating clips with hate speech, explicit content, or dangerous material. Current branch has ZERO content moderation — LLMs produce titles, hook captions, and hashtags from transcripts that may contain harmful content. This is a **serious gap** for platform compliance (TikTok/YouTube/Reels all have strict content policies).

#### Files Needed
- `app/core/moderation.py` (46 lines, self-contained)

#### Dependencies
- None — pure Python regex, no external libraries
- Does NOT depend on any main-branch config/auth/DB modules

#### Merge Risk
**LOW**

#### Integration Notes
1. Copy `flag_safety_issues()` and `moderate_clips()` into current codebase
2. Create `services/moderation.py` (to match current branch convention)
3. Call `moderate_clips()` in `services/clipping.py` `_run_analyze_transcript()` after cross-model judging and before the final `top_clips` return
4. Update the `_SAFETY_BLOCKLIST` patterns — the current list is minimal. Add comprehensive patterns based on platform policy needs
5. Wire moderation results into `clip.quality_filter_results` JSON for QA dashboard visibility
6. Add `moderation_bypassed` flag to allow admin overrides in QA tool

#### Do NOT Import
- Nothing else from main branch — this file is completely standalone

---

### Feature 2: Circuit Breaker Pattern for AI Providers
**Source:** `app/core/circuit_breaker.py` (origin/main)
**Status:** NOT present in current branch. Current has only rate-limit fallback, not circuit breaker

#### Why It Matters
Current branch has `try_with_rate_limit_fallback()` in `services/config.py` which catches Groq 429 → falls back to OpenAI. But it **retries every time** — if both providers are down, every LLM call burns retry budget with no chance of success. The circuit breaker remembers consecutive failures in Redis and auto-skips to fallback after N failures without wasting retry cycles.

#### Files Needed
- `app/core/circuit_breaker.py` (97 lines, only depends on Redis client)

#### Dependencies
- Requires access to a Redis client (current branch already has `redis_conn` in `workers/queue.py`)
- No other dependencies

#### Merge Risk
**LOW**

#### Integration Notes
1. Create `services/circuit_breaker.py`
2. Initialize with `from workers.queue import redis_conn`
3. Wrap `_run_analyze_transcript()` in `services/clipping.py`:
   ```python
   breaker = CircuitBreaker(redis_conn)
   if breaker.is_open(provider):
       fallback = breaker.should_fallback(provider, alternate_provider)
       if fallback:
           provider = fallback
   ```
4. Add `breaker.record_failure(provider)` to exception handlers
5. Add `breaker.record_success(provider)` to success paths
6. Expose breaker status via `GET /api/metrics` for monitoring

#### Do NOT Import
- Nothing else — standalone utility

---

### Feature 3: Environment-Aware Structured Logging
**Source:** `app/core/logging_config.py` (origin/main)
**Status:** Partially present. Current has `services/logging.py` (45 lines, basic JSON logger) but missing request tracing, PII redaction, context propagation, and Sentry/OpenTelemetry hooks

#### Why It Matters
Current branch's logging is minimal. The main branch has a production-grade logging system with:
- `request_id` / `correlation_id` / `user_id` context propagation via contextvars
- PII redaction (API keys, tokens, passwords)
- Sentry integration with sanitized event payloads
- OpenTelemetry tracing hooks
- Dev vs. production format switching

This matters for debugging production issues — without correlation IDs, you can't trace a single request across the pipeline.

#### Files Needed
- `app/core/logging_config.py` (228 lines, mostly standalone)

#### Dependencies
- `sentry-sdk` (optional, already documented as optional)
- `opentelemetry-*` packages (optional)
- Python `contextvars` (stdlib)
- No DB or auth module dependencies

#### Merge Risk
**LOW** (for the core logging without Sentry/OTel)

#### Integration Notes
1. Create `services/logging_config.py` (rename to avoid confusion with current `services/logging.py`)
2. Call `setup_logging()` at startup in `api/main.py`
3. Keep the current `JobLogger` class, but make it use the structured formatter
4. Add `set_request_context()` call to the middleware (requires creating middleware — see Feature 5)
5. Sentry/OTel are optional — only enable if env vars are set
6. The `sanitize_dict()` function is valuable standalone — can be used anywhere sensitive data is logged

#### Do NOT Import
- `sentry-sdk` or `opentelemetry` unless user wants to set them up

---

### Feature 4: Cut Aligner with Directional Snapping
**Source:** `app/core/cut_aligner.py` (origin/main)
**Status:** Partially present. Current has `services/clipping.py` → `snap_to_silence()` and `align_clip_boundaries()`, but main branch version has **directional snapping** (start → backward, end → forward) and a **10s minimum clip guard**

#### Why It Matters
Current branch's `snap_to_silence()` uses `direction="nearest"` for ALL boundaries and an 8s minimum. The main branch version:
- Snaps clip **start** backward (ensure you don't cut into the beginning of a sentence)
- Snaps clip **end** forward (ensure you don't cut off the last word)
- Uses 10s minimum (vs. 8s — more conservative, higher quality)

Directional snapping is objectively better — snapping "nearest" for start can cut into the first word, ruining the hook.

#### Files Needed
- Only the `direction` parameter logic from `snap_to_silence()` — not the entire file

#### Dependencies
- None — drop-in replacement

#### Merge Risk
**LOW**

#### Integration Notes
1. Update `services/clipping.py` `snap_to_silence()` to add `direction` parameter
2. Update `align_clip_boundaries()` to pass `direction='start'` for context_start/hook_start and `direction='end'` for payoff_end
3. Change min clip guard from 8s to 10s
4. Keep all other current branch logic (semantic dedup, filter integration, etc.)

#### Do NOT Import
- The entire file — just extract the direction parameter logic

---

### Feature 5: Request Logging Middleware with Security Headers
**Source:** `app/api/middleware.py` (origin/main)
**Status:** NOT present in current branch

#### Why It Matters
Current branch has NO middleware at all — no security headers, no request tracing, no timing. This means:
- No CORS refinements (current: `allow_origins=["*"]`)
- No security headers (clickjacking, MIME sniffing, referrer leakage)
- No request timing metrics
- No correlation ID propagation

#### Files Needed
- `app/api/middleware.py` (adapt, don't copy directly)

#### Dependencies
- `app/core/logging_config.py` for `set_request_context()`/`clear_request_context()`
- `app.api.auth` for user ID extraction (current branch has no auth — skip this part)
- `fastapi.Request`, `starlette.middleware.base.BaseHTTPMiddleware`

#### Merge Risk
**MEDIUM** — security headers need testing on current branch's frontend to ensure CSP doesn't break Next.js

#### Integration Notes
1. Create `api/middleware.py`
2. Add middleware to FastAPI app:
   ```python
   app.add_middleware(RequestLoggingMiddleware)
   ```
3. **Skip the `app.api.auth` import** — current branch has no auth system. Replace user ID extraction with a no-op or use a placeholder
4. **Relax the CSP** — current `Content-Security-Policy` in main branch blocks ALL scripts/styles/images/fonts. This will break the Next.js frontend completely
5. Start with a minimal CSP:
   ```python
   "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self' ws://localhost:*;"
   ```
6. Add request duration to structured logging
7. **Keep existing CORS config** — don't replace, just complement

#### Do NOT Import
- `app.api.auth` import logic
- The Supabase user lookup
- The `DEV_MODE` dev-token logic
- `app.config` imports — use current branch's `services/config.py` instead

---

## Section B: MEDIUM COMPLEXITY INTEGRATIONS (Moderate Risk, High Value)

### Feature 6: Rate Limiter
**Source:** `app/api/rate_limiter.py` (origin/main)
**Status:** NOT present in current branch. All endpoints are unauthenticated and unlimited

#### Why It Matters
Without rate limiting, the API is vulnerable to:
- Upload spam (costly — each upload triggers Whisper + LLM costs)
- WebSocket flood (connection exhaustion)
- Clip download abuse (bandwidth costs)

The main branch has a clean Redis-based rate limiter with per-user and per-IP modes and proper 429 responses with `Retry-After` headers.

#### Files Needed
- `app/api/rate_limiter.py`

#### Dependencies
- `app.config` → `get_redis_async()` (needs Redis async client)
- `fastapi.Request`, `fastapi.WebSocket`

#### Merge Risk
**MEDIUM** — requires Redis async client setup and wiring into existing endpoints

#### Integration Notes
1. Create `api/rate_limiter.py`
2. The main branch uses `redis.asyncio` — current branch uses synchronous `redis.Redis`. Either:
   - Switch to async Redis, OR
   - Adapt rate limiter to use synchronous Redis
   - **Recommendation:** Adapt to sync — current branch is fully synchronous with RQ
3. Wrap upload endpoint: `rate_limit_by_ip(request, "upload", limit=5, window_seconds=300)`
4. Wrap clip download: `rate_limit_by_ip(request, "download", limit=20, window_seconds=60)`
5. Wrap WebSocket connect: `rate_limit_by_ip(request, "ws_connect", limit=10, window_seconds=60)`
6. Add `GET /api/metrics` endpoint with rate limit stats (breaker status, queue stats already present)

#### Do NOT Import
- `app.config.get_redis_async` — use synchronous Redis from `workers/queue.py`

---

### Feature 7: B-Roll Overlay Module
**Source:** `app/core/broll.py` (origin/main)
**Status:** NOT present in current branch

#### Why It Matters
B-roll overlays (stock footage cutaways) DRAMATICALLY improve viewer retention. Instead of watching 60s of a talking head, viewers see relevant visuals. The main branch has a complete Pexels integration — keyword extraction from transcript → search → download → FFmpeg overlay with fade transitions.

#### Files Needed
- `app/core/broll.py` (218 lines)

#### Dependencies
- `PEXELS_API_KEY` env var (optional — no-op if not set)
- `requests` (already in current branch's requirements.txt)
- `app.config.FFMPEG_TIMEOUT_SECONDS` → `services.config.FFMPEG_TIMEOUT_SECONDS`

#### Merge Risk
**MEDIUM** — needs integration into the render pipeline

#### Integration Notes
1. Create `services/broll.py`
2. Replace `app.config` import with `services.config`
3. Integrate into `workers/pipeline_worker.py` `_h_render_started`:
   - After `safe_create_clip()` renders a clip
   - Call `apply_broll(clip_path, clip_info, transcript_words, transcript_text, work_dir, pexels_key)`
   - If B-roll applied successfully, use the broll path instead of the original
   - Update `_build_clip_entry()` and `_persist_clip()` to reference the broll path
4. Add B-roll toggle to upload form (`app/upload/page.tsx`) or make it a per-preset option
5. The keyword mapping (`BROLL_KEYWORD_MAP`) is a great foundation but should be expanded
6. Add `PEXELS_API_KEY` to `.env.example`

#### Do NOT Import
- `app.config` — only the FFmpeg timeout constant is needed

---

### Feature 8: Subscription Tier Plans & Usage Tracking
**Source:** `app/core/plans.py`, `app/services/credits.py` (origin/main)
**Status:** NOT present in current branch. No billing, no usage tracking

#### Why It Matters
Current branch has zero monetization infrastructure. The main branch has:
- 4-tier subscription model (Trial/Pro/Studio/Agency)
- Per-minute usage tracking and enforcement
- Credit packs
- Usage records

#### Files Needed
- `app/core/plans.py`
- `app/services/credits.py`
- `app/config.py` SUBSCRIPTION_TIERS and usage config

#### Dependencies
- User model columns: `total_minutes_limit`, `used_minutes`, `rollover_credits`, `subscription_tier`
- DB table: `usage_records`
- `app/models/models.py` User model
- `app/security/rbac.py` for `can_bypass_credits()`
- Razorpay integration for billing (separate — only include if implementing full billing)

#### Merge Risk
**HIGH** — requires database schema changes and auth system

#### Integration Notes
1. This is a **feature, not a utility** — it's a significant undertaking
2. Minimum viable integration:
   - Add `total_minutes_limit`, `used_minutes` columns to User/Job models
   - Record usage per job via `record_usage()` after `_h_export_completed`
   - Enforce limit via `require_credit_access()` before `POST /api/upload`
   - Skip billing integration (Razorpay) until auth/user management exists
3. The plan definitions in `app/config.py` are clean and reusable
4. Do NOT port the RBAC module — use simple plan-checking without full role-based access control

#### Do NOT Import
- `app/security/rbac.py` — current branch has no auth, RBAC is overkill
- `app/api/payments.py` — Razorpay integration, needs full auth system
- `app/api/auth.py` — Supabase auth, conflicts with no-auth current architecture

---

## Section C: FEATURES THAT SHOULD NOT BE PORTED

### X1: `app/core/analyzer.py` — OLD LLM Analysis
**Reason:** Current branch's `services/clipping.py` is a DRAMATICALLY better version with cross-model judging, pre-LLM signals, psychology scoring, dynamic context windows, and 7 rule-based filters. The main branch's analyzer is a single-pass LLM call with a simpler prompt and no quality controls. DO NOT downgrade.

### X2: `app/core/downloader.py` — OLD yt-dlp Downloader
**Reason:** Current branch's `services/downloader.py` is already better — it has quality tiers (audio_only/proxy/full), content-addressed caching with SHA-256 hash, resume support, and multi-pass fallback. Main branch's version is simpler and has no caching.

### X3: `app/subtitles/transcriber.py` — OLD Transcription
**Reason:** Current branch's `services/whisper.py` is nearly identical but with better error handling and provider auto-fallback. Same feature, no advantage to porting.

### X4: `app/core/storage.py` — OLD S3-Only Storage
**Reason:** Current branch's `services/storage.py` is superior — it has an ABC-based architecture with both LocalStorageBackend and SupabaseStorageBackend. Main branch only has S3 via boto3. Current branch is more flexible and abstract.

### X5: `app/core/preflight.py` — DUPLICATE Video Tool Checks
**Reason:** Current branch already has `services/ffmpeg.py` → `get_video_info()` and validation in pipeline stages. The preflight checks are already covered in `_h_metadata_fetched()` and `_h_download_completed()`.

### X6: `app/config.py` — OLD Config System
**Reason:** Current branch's `services/config.py` is cleaner and more focused. Main branch's `app/config.py` is a massive file (500+ lines) with billing, subscription tiers, Razorpay, 4K presets, Sentry, OpenTelemetry, and validation — most of which depends on auth and billing systems that don't exist in current branch. Extract only individual constants as needed, never the whole file.

### X7: `app/api/main.py` — OLD API Server
**Reason:** Completely different architecture. Main branch uses Celery workers, has auth endpoints, payment endpoints, and a different data model. Current branch's `api/main.py` is its own complete system with the RQ pipeline.

### X8: `app/workers/` — CELERY Workers
**Reason:** Current branch uses RQ, not Celery. The RQ architecture (staged queues, idempotent stages, per-stage retry) is better designed. Do not mix queue systems.

### X9: `app/security/rbac.py` — Role-Based Access Control
**Reason:** Current branch has NO authentication system. Adding RBAC without auth is meaningless. This belongs to a future auth implementation, not the current porting effort.

### X10: `app/api/auth.py`, `app/api/payments.py`, `app/api/admin.py`
**Reason:** Depend on Supabase auth, Razorpay, and RBAC modules — none exist in current branch.

### X11: `app/services/feature_flags.py`
**Reason:** Depends on RBAC module. Current branch has no concept of user roles or plans.

### X12: `app/models/models.py`
**Reason:** Different ORM conventions. Current branch's `api/models.py` is already set up with the right columns. Main branch's User model is auth-heavy with columns not relevant to current branch.

---

## Section D: EXECUTION PLAN

### Phase 1 — Safe Quick Wins (Today)
1. **Copy moderation** → `services/moderation.py`
2. **Copy circuit breaker** → `services/circuit_breaker.py`  
3. **Integrate directional snapping logic** → update `services/clipping.py`
4. **Integrate moderation into clipping pipeline** → update `services/clipping.py`
5. **Integrate circuit breaker into clipping pipeline** → update `services/clipping.py`

### Phase 2 — Medium Complexity (This Week)
6. **Copy logging config** → `services/logging_config.py`
7. **Wire logging into FastAPI startup** → update `api/main.py`
8. **Create API middleware with security headers** → `api/middleware.py`
9. **Wire middleware into FastAPI app** → update `api/main.py`
10. **Copy rate limiter** → `api/rate_limiter.py`
11. **Wire rate limiting into key endpoints** → update `api/main.py`

### Phase 3 — Feature Additions (Next Sprint)
12. **Copy B-roll module** → `services/broll.py`
13. **Integrate B-roll into render pipeline** → update `workers/pipeline_worker.py`
14. **Add B-roll toggle to upload form** → update `app/upload/page.tsx`
15. **Copy plan definitions** → `services/plans.py`
16. **Add usage tracking to DB** → Alembic migration + `api/models.py`

### Phase 4 — Deferred (Requires Auth System First)
- Subscription enforcement → depends on `POST /api/upload` having authenticated users
- Full billing → depends on auth + Razorpay setup
- RBAC → depends on auth + user roles
- Feature flags → depends on RBAC

---

## Summary Table

| File to Port | New Location | Risk | Effort | Value |
|---|---|---|---|---|
| `app/core/moderation.py` | `services/moderation.py` | LOW | 30min | HIGH — compliance gap |
| `app/core/circuit_breaker.py` | `services/circuit_breaker.py` | LOW | 1hr | HIGH — reliability |
| `cut_aligner.py` direction logic | Update `services/clipping.py` | LOW | 30min | MEDIUM — quality improvement |
| `app/core/logging_config.py` | `services/logging_config.py` | LOW | 2hr | MEDIUM — observability |
| `app/api/middleware.py` | `api/middleware.py` | MEDIUM | 2hr | MEDIUM — security |
| `app/api/rate_limiter.py` | `api/rate_limiter.py` | MEDIUM | 3hr | HIGH — abuse prevention |
| `app/core/broll.py` | `services/broll.py` | MEDIUM | 4hr | MEDIUM — retention boost |
| `app/core/plans.py` | `services/plans.py` | HIGH | 6hr | MEDIUM — future monetization |
| `app/services/credits.py` | `services/credits.py` | HIGH | 6hr | MEDIUM — future monetization |
