"""
Optimized Video Downloader — Quality tiers, content-addressed caching, resume support.
Uses yt-dlp with concurrent fragment downloads and hash-based dedup.
"""
import os
import shutil
import hashlib
import logging
import time
import yt_dlp

logger = logging.getLogger(__name__)

QUALITY_TIERS = {
    "audio_only": "bestaudio[ext=m4a]/bestaudio/best",
    "proxy": (
        "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
        "best[height<=720][ext=mp4]/best"
    ),
    "full": (
        "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
        "best[height<=1080][ext=mp4]/best"
    ),
}

CACHE_DIR = os.path.join("storage", "cache")


def download_video(url: str, output_path: str, quality: str = "proxy",
                    progress_cb=None) -> str:
    """
    Download video with quality tier, resume, and content-addressed caching.

    Args:
        url: Video URL to download
        output_path: Destination file path
        quality: 'audio_only', 'proxy' (720p), or 'full' (1080p)
        progress_cb: Optional callback(msg, pct)
    Returns: output_path
    """
    source_hash = _hash_url(url)
    cache_path = os.path.join(CACHE_DIR, f"{source_hash}_{quality}.mp4")

    # ── Cache hit ─────────────────────────────────────────────
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        logger.info("Cache HIT for %s (%s)", url[:80], quality)
        if progress_cb:
            progress_cb("Restored from cache", 100)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(cache_path, output_path)
        return output_path

    # ── Download ──────────────────────────────────────────────
    format_str = QUALITY_TIERS.get(quality, QUALITY_TIERS["proxy"])

    if progress_cb:
        progress_cb(f"Starting {quality} quality download...", 2)

    def progress_hook(d):
        if d.get("status") == "downloading" and progress_cb:
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "")
            eta = d.get("_eta_str", "")
            progress_cb(f"Downloading: {pct} @ {speed} ETA {eta}", 3)

    ydl_opts = {
        "format": format_str,
        "outtmpl": output_path,
        "continuedl": True,                    # Resume partial downloads
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 15,
        "fragment_retries": 15,
        "concurrent_fragment_downloads": 8,    # Parallel DASH segments
        "nokeepalive": True,                   # Prevent CDN keepalive channel closures
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
        "progress_hooks": [progress_hook],
    }

    # Multi-pass: try quality tier, then fallback to unified format
    attempts = [
        ydl_opts,
        {**ydl_opts, "format": "best[ext=mp4]/best"},
    ]

    last_error = None
    for i, opts in enumerate(attempts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            break
        except Exception as e:
            logger.warning("Download attempt %d failed: %s", i + 1, e)
            last_error = e
            if i < len(attempts) - 1:
                time.sleep(3)
    else:
        raise RuntimeError(f"URL download failed after {len(attempts)} attempts: {last_error}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise FileNotFoundError("Download completed but file missing or empty")

    # ── Cache for future ──────────────────────────────────────
    os.makedirs(CACHE_DIR, exist_ok=True)
    shutil.copy2(output_path, cache_path)
    logger.info("Cached → %s", cache_path)

    if progress_cb:
        progress_cb("Download complete", 15)

    return output_path


def _hash_url(url: str) -> str:
    """Content-addressable cache key from URL"""
    return hashlib.sha256(url.strip().encode()).hexdigest()[:16]


def get_cache_path(url: str, quality: str = "proxy") -> str:
    """Return expected cache path for a URL (doesn't guarantee existence)"""
    return os.path.join(CACHE_DIR, f"{_hash_url(url)}_{quality}.mp4")


def has_cached(url: str, quality: str = "proxy") -> bool:
    """Check if URL+quality combo is cached"""
    path = get_cache_path(url, quality)
    return os.path.exists(path) and os.path.getsize(path) > 0
