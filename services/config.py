"""
Shared configuration constants — single source of truth for timeouts and API settings.
"""
import os

# FFmpeg timeouts
FFMPEG_TIMEOUT_SECONDS = float(os.getenv("FFMPEG_TIMEOUT_SECONDS", 300.0))
FFPROBE_TIMEOUT_SECONDS = float(os.getenv("FFPROBE_TIMEOUT_SECONDS", 30.0))
THUMBNAIL_TIMEOUT_SECONDS = float(os.getenv("THUMBNAIL_TIMEOUT_SECONDS", 30.0))

# AI API timeouts
AI_API_TIMEOUT_SECONDS = float(os.getenv("AI_API_TIMEOUT_SECONDS", 120.0))
AI_API_MAX_RETRIES = int(os.getenv("AI_API_MAX_RETRIES", 2))

# Whisper settings
AUDIO_CHUNK_DURATION = int(os.getenv("AUDIO_CHUNK_DURATION", 600))
WHISPER_MAX_FILE_SIZE = int(os.getenv("WHISPER_MAX_FILE_SIZE", 24 * 1024 * 1024))

# LLM provider configurations
LLM_PROVIDERS = {
    'openai': {
        'base_url': None,
        'whisper_model': 'whisper-1',
        'llm_model': 'gpt-4o-mini',
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai/v1',
        'whisper_model': 'whisper-large-v3-turbo',
        'llm_model': 'llama-3.1-8b-instant',
    },
}


def resolve_api_keys(preferred_provider: str):
    """
    Resolves which API provider and key to use.
    Returns (provider, api_key) — auto-falls back if preferred provider key is missing.
    Raises ValueError if neither key is configured.
    """
    import logging
    logger = logging.getLogger(__name__)

    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    provider = preferred_provider
    api_key = groq_key if provider == 'groq' else openai_key

    if provider == 'groq' and not groq_key:
        if openai_key:
            logger.info("Groq API key not set. Switching to OpenAI.")
            provider = 'openai'
            api_key = openai_key
        else:
            raise ValueError(
                "Neither GROQ_API_KEY nor OPENAI_API_KEY is configured in your environment."
            )
    elif provider == 'openai' and not openai_key:
        if groq_key:
            logger.info("OpenAI API key not set. Switching to Groq.")
            provider = 'groq'
            api_key = groq_key
        else:
            raise ValueError(
                "Neither GROQ_API_KEY nor OPENAI_API_KEY is configured in your environment."
            )

    if not api_key:
        raise ValueError("Missing API key for AI processing.")

    return provider, api_key


def try_with_rate_limit_fallback(provider, api_key, openai_key, func, *args, **kwargs):
    """
    Runs func(key, ...). If Groq returns rate-limit error, retries with OpenAI.
    Returns whatever func returns.
    """
    import logging
    import time
    logger = logging.getLogger(__name__)

    try:
        return func(api_key, *args, **kwargs)
    except Exception as e:
        err_msg = str(e).lower()
        if provider == 'groq' and ("rate_limit" in err_msg or "429" in err_msg or "rate limit" in err_msg):
            if openai_key:
                logger.warning("Groq rate limit hit. Falling back to OpenAI.")
                try:
                    return func(openai_key, *args, **kwargs)
                except Exception as openai_err:
                    raise RuntimeError(
                        f"Groq rate limit exceeded and OpenAI fallback also failed: {openai_err}"
                    ) from openai_err
            else:
                raise RuntimeError(
                    f"Groq rate limit exceeded. Set OPENAI_API_KEY to enable automatic fallback. Details: {e}"
                ) from e
        raise e
