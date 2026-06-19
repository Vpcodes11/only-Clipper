# ?? FUTURE.md — Only Clipper Roadmap

> **Vision**: Become the most powerful AI clip engine on the planet — not just for podcasts, but for every type of video humans watch.

---

## ?? Where We Are Today (v1.0)

- ? Full pipeline: URL ? Download ? Transcribe ? AI Analysis ? Render ? Export
- ? Viral clip detection from speech/interviews/podcasts
- ? Auto captions on clips
- ? Virality scoring + hook detection
- ? Semantic deduplication (no repeat clips)
- ? REST API + WebSocket progress updates
- ? Vision-based analysis (sports, action, non-speech video)
- ? Face tracking / speaker zoom
- ? Multi-format export (9:16, 1:1, 16:9)
- ? Speed (bottlenecked by Groq free tier rate limits)

---

## ?? Phase 1 — Polish & Speed (Next 30 Days)

**Goal**: Make what we have fast, reliable, and production-ready.

### 1.1 Fix the Rate Limit Problem
- [ ] Add support for **paid Groq key** (removes 6K TPM cap ? 100K TPM)
- [ ] Add **OpenAI fallback** when Groq is rate-limited
- [ ] Add **parallel chunk processing** (analyze multiple chunks simultaneously)
- [ ] Expected speedup: **10x faster** on 1-hour videos

### 1.2 Better Clip Quality
- [ ] Improve the Judge prompt — score clips more accurately
- [ ] Add **minimum clip duration filter** (remove clips < 15s that are useless)
- [ ] Add **maximum clip duration filter** (cap at 90s for TikTok/Reels)
- [ ] Filter out clips with low energy/flat tone

### 1.3 Multi-Format Export
- [ ] **9:16 vertical** (TikTok, Instagram Reels, YouTube Shorts)
- [ ] **1:1 square** (Twitter/X, LinkedIn)
- [ ] **16:9 horizontal** (YouTube, LinkedIn)
- [ ] Let user choose format at job creation time

### 1.4 UI Improvements
- [ ] Real-time progress bar that actually updates during analysis
- [ ] Preview thumbnails for each clip in the dashboard
- [ ] One-click download of all clips as a ZIP
- [ ] Show clip start/end time and virality score on the card

---

## ?? Phase 2 — Vision Pipeline (60–90 Days)

**Goal**: Support non-speech video — sports, gaming, cooking, travel vlogs.

> This is the gap between us and Opus Clip. This phase closes it.

### 2.1 Audio Energy Analysis
- [ ] Detect **excitement peaks** from audio waveform (no speech needed)
- [ ] Crowd roar detection for sports
- [ ] Music drop detection for gaming/highlights
- [ ] Commentary pitch/energy scoring

### 2.2 Vision Frame Analysis
- [ ] Sample frames every N seconds
- [ ] Send frames to **GPT-4o Vision** or **Gemini 2.0 Flash** (cheapest vision model)
- [ ] Detect: goals, celebrations, crashes, big moments, reaction faces
- [ ] Build a "visual excitement score" per timestamp

### 2.3 Hybrid Pipeline
- [ ] Auto-detect video type: speech-heavy vs action-heavy vs mixed
- [ ] Route to correct pipeline automatically:
  - Speech-heavy ? Transcript pipeline (current)
  - Action-heavy ? Vision pipeline (new)
  - Mixed ? Both pipelines, merge results
- [ ] Works for: football, cricket, gaming, cooking shows, travel vlogs, podcasts

### 2.4 New Video Types Supported After Phase 2

| Video Type | Method |
|---|---|
| Football / Cricket | Audio energy + vision |
| Gaming highlights | Audio energy + vision |
| Cooking shows | Vision + light transcript |
| Travel vlogs | Vision + transcript |
| Podcasts / Interviews | Transcript (already works) |
| Motivational speeches | Transcript (already works) |
| News segments | Transcript + vision |

---

## ?? Phase 3 — Face Tracking & Smart Framing (90–120 Days)

**Goal**: Clips should look professional, not like raw cuts.

### 3.1 Speaker Detection
- [ ] Detect who is speaking at any timestamp
- [ ] Auto-zoom to the active speaker face
- [ ] Switch framing when speaker changes (interview format)

### 3.2 Smart Crop
- [ ] Always keep face in frame during vertical (9:16) export
- [ ] Auto-reframe landscape to portrait without cutting off the subject
- [ ] Handle multi-person frames (panel shows, debates)

### 3.3 B-Roll Support
- [ ] Allow user to overlay B-roll clips on top of audio
- [ ] Auto-suggest B-roll based on transcript keywords

---

## ?? Phase 4 — Platform Intelligence (120–180 Days)

**Goal**: Don't just clip — optimize for the platform the clip will be posted on.

### 4.1 Platform Profiles
- [ ] **TikTok mode**: max 60s, strong hook in first 3s, trending audio
- [ ] **YouTube Shorts mode**: max 60s, optimized title/description
- [ ] **Instagram Reels mode**: visual-first, minimal text
- [ ] **LinkedIn mode**: professional tone, longer form (up to 3min)
- [ ] **Twitter/X mode**: punchy, under 30s

### 4.2 Auto Title + Caption Generation
- [ ] Generate platform-specific titles for each clip
- [ ] Generate hashtag sets per platform
- [ ] Generate hook text overlay for first 3 seconds
- [ ] Generate description copy for posting

### 4.3 Trend Awareness
- [ ] Pull trending topics from each platform
- [ ] Score clips higher if they match current trends
- [ ] Suggest optimal posting times

---

## ?? Phase 5 — Direct Publishing & Analytics (180+ Days)

**Goal**: Go from clip to published in one click. Then learn from performance.

### 5.1 Direct Publishing
- [ ] Connect TikTok account ? post clips directly
- [ ] Connect Instagram ? post to Reels directly
- [ ] Connect YouTube ? post as Shorts directly
- [ ] Schedule posts (post at optimal time automatically)

### 5.2 Performance Analytics
- [ ] Pull view counts, likes, shares back into the dashboard
- [ ] Show which clips performed best
- [ ] Learn from performance ? improve future clip selection (feedback loop)
- [ ] A/B test different clip versions

### 5.3 Team & Agency Features
- [ ] Multiple users per workspace
- [ ] Assign clips to team members for review
- [ ] Approval workflow before publishing
- [ ] White-label dashboard for agencies

---

## ?? End Goal: What We Become

| Today | Future |
|---|---|
| Podcast/interview clipper | Universal video clip engine |
| Manual URL input | Bulk upload, YouTube channel sync |
| One pipeline | Transcript + Vision + Audio pipelines |
| Local/self-hosted | SaaS product with subscriptions |
| No publishing | Direct publish to 5+ platforms |
| No analytics | Full performance feedback loop |

---

## ?? Monetization Path

| Tier | Price | Limit | Features |
|---|---|---|---|
| **Free** | $0 | 5 clips/month | Transcript pipeline only, watermark |
| **Creator** | $19/month | 50 videos/month | All pipelines, no watermark, 3 platforms |
| **Pro** | $49/month | 200 videos/month | Everything + direct publishing + analytics |
| **Agency** | $199/month | Unlimited | Team features, white-label, API access |

---

## ??? Tech Debt to Fix Along the Way

- [ ] Move from SQLite to PostgreSQL for production scale
- [ ] Add proper job retry UI (currently only CLI-level)
- [ ] Replace rq with Celery for better task visibility
- [ ] Add proper logging/monitoring (Sentry, Datadog)
- [ ] Write unit tests for clipping pipeline
- [ ] Dockerize the full stack for easy deployment
- [ ] Move to cloud storage (S3/R2) instead of local disk

---

*Last updated: June 2026*
*Current version: v1.0 — Transcript Pipeline*
