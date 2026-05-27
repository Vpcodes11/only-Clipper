"""Transcription module — supports Groq Whisper (free) and OpenAI Whisper"""
import subprocess
import os
import json
import time
import logging
from openai import OpenAI
from services.config import (
    AUDIO_CHUNK_DURATION, AI_API_MAX_RETRIES, AI_API_TIMEOUT_SECONDS,
    FFMPEG_TIMEOUT_SECONDS, FFPROBE_TIMEOUT_SECONDS, WHISPER_MAX_FILE_SIZE,
    LLM_PROVIDERS, resolve_api_keys, try_with_rate_limit_fallback,
)

logger = logging.getLogger(__name__)

PROVIDERS = {
    'openai': {
        'base_url': None,
        'whisper_model': 'whisper-1',
        'supports_word_timestamps': True,
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai/v1',
        'whisper_model': 'whisper-large-v3-turbo',
        'supports_word_timestamps': True,
    }
}


def get_client(api_key, provider='groq'):
    """Create OpenAI-compatible client for the chosen provider"""
    config = PROVIDERS.get(provider, PROVIDERS['groq'])
    kwargs = {'api_key': api_key}
    if config['base_url']:
        kwargs['base_url'] = config['base_url']
    return OpenAI(timeout=AI_API_TIMEOUT_SECONDS, max_retries=0, **kwargs), config


def extract_audio(video_path, audio_path):
    """Extract audio from video as mono MP3 at 64kbps (compact file size for API limits)"""
    logger.info("Extracting audio from video: %s -> %s", video_path, audio_path)
    cmd = [
        'ffmpeg', '-i', video_path,
        '-vn', '-ac', '1', '-ab', '64k',
        '-f', 'mp3', '-y', audio_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Audio extraction timed out.") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-300:]}")


def get_media_duration(path):
    """Get duration of a media file (audio/video) in seconds using ffprobe"""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'json', path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=FFPROBE_TIMEOUT_SECONDS)
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        logger.error("Failed to get duration via ffprobe: %s", e)
        raise RuntimeError(f"Failed to analyze media duration: {e}") from e


def split_audio(audio_path, chunk_dir, chunk_duration=AUDIO_CHUNK_DURATION):
    """Split audio into chunks to stay under Whisper API file size limits"""
    duration = get_media_duration(audio_path)
    chunks = []
    start = 0
    i = 0
    while start < duration:
        chunk_path = os.path.join(chunk_dir, f"chunk_{i:03d}.mp3")
        cmd = [
            'ffmpeg', '-i', audio_path,
            '-ss', str(start), '-t', str(chunk_duration),
            '-acodec', 'copy', '-y', chunk_path
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=FFMPEG_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Audio chunk split timed out.") from exc
        chunks.append((chunk_path, start))
        start += chunk_duration
        i += 1
    return chunks


def _transcribe_file(client, config, file_path):
    """Transcribe a single audio file, handling word-timestamp extractions"""
    logger.info("Uploading file to Whisper API: %s using model %s", os.path.basename(file_path), config['whisper_model'])
    with open(file_path, 'rb') as f:
        kwargs = {
            'model': config['whisper_model'],
            'file': f,
            'response_format': 'verbose_json',
        }
        if config['supports_word_timestamps']:
            kwargs['timestamp_granularities'] = ["word", "segment"]

        response = None
        for attempt in range(AI_API_MAX_RETRIES + 1):
            try:
                response = client.audio.transcriptions.create(**kwargs)
                break
            except Exception as exc:
                if attempt >= AI_API_MAX_RETRIES:
                    raise exc
                delay = min(8, 2 ** attempt)
                logger.warning("Transcription retry attempt=%s file=%s error=%s", attempt + 1, os.path.basename(file_path), exc)
                time.sleep(delay)

    if response is None:
        raise RuntimeError("Transcription API returned no response.")

    words = []
    segments = []

    # Extract word timestamps
    if hasattr(response, 'words') and response.words:
        for word in response.words:
            # Handle object response or dictionary format
            if isinstance(word, dict):
                words.append({
                    'word': word.get('word', ''),
                    'start': float(word.get('start', 0.0)),
                    'end': float(word.get('end', 0.0))
                })
            else:
                words.append({
                    'word': getattr(word, 'word', ''),
                    'start': float(getattr(word, 'start', 0.0)),
                    'end': float(getattr(word, 'end', 0.0))
                })

    # Extract segment details
    if hasattr(response, 'segments') and response.segments:
        for seg in response.segments:
            if isinstance(seg, dict):
                segments.append({
                    'text': seg.get('text', ''),
                    'start': float(seg.get('start', 0.0)),
                    'end': float(seg.get('end', 0.0))
                })
            else:
                segments.append({
                    'text': getattr(seg, 'text', ''),
                    'start': float(getattr(seg, 'start', 0.0)),
                    'end': float(getattr(seg, 'end', 0.0))
                })

    # Fallback: if no word-level timestamps, interpolate from segment text
    if not words and segments:
        logger.info("No word-level timestamps returned. Interpolating from segment text.")
        for seg in segments:
            seg_words = seg['text'].strip().split()
            if not seg_words:
                continue
            duration = seg['end'] - seg['start']
            word_dur = duration / len(seg_words)
            for j, w in enumerate(seg_words):
                words.append({
                    'word': w,
                    'start': seg['start'] + j * word_dur,
                    'end': seg['start'] + (j + 1) * word_dur
                })

    return words, segments


def _run_transcribe(video_path, api_key, progress_callback=None, provider='groq'):
    """Full execution of the transcription steps"""
    client, config = get_client(api_key, provider)

    # Setup work directory in the temp folder
    temp_dir = os.getenv("TEMP_DIR", "./temp")
    job_id = os.path.basename(os.path.dirname(video_path))
    work_dir = os.path.join(temp_dir, job_id, "work")
    os.makedirs(work_dir, exist_ok=True)
    audio_path = os.path.join(work_dir, "audio.mp3")

    if progress_callback:
        progress_callback("Extracting audio from video...", 5)
    extract_audio(video_path, audio_path)

    file_size = os.path.getsize(audio_path)
    all_words = []
    all_segments = []

    if file_size > WHISPER_MAX_FILE_SIZE:
        if progress_callback:
            progress_callback("Audio is large, splitting into segments...", 10)
        chunks = split_audio(audio_path, work_dir)
        total_chunks = len(chunks)

        for idx, (chunk_path, offset) in enumerate(chunks):
            if progress_callback:
                pct = 15 + int((idx / total_chunks) * 40)
                progress_callback(f"Transcribing chunk {idx+1}/{total_chunks}...", pct)

            words, segments = _transcribe_file(client, config, chunk_path)

            # Adjust timestamps with chunk offset
            for w in words:
                all_words.append({
                    'word': w['word'],
                    'start': w['start'] + offset,
                    'end': w['end'] + offset
                })
            for s in segments:
                all_segments.append({
                    'text': s['text'],
                    'start': s['start'] + offset,
                    'end': s['end'] + offset
                })
    else:
        if progress_callback:
            progress_callback("Transcribing audio via Whisper...", 15)

        words, segments = _transcribe_file(client, config, audio_path)
        all_words = words
        all_segments = segments

    if progress_callback:
        progress_callback("Transcription complete!", 55)

    try:
        duration = get_media_duration(video_path)
    except Exception:
        duration = all_segments[-1]['end'] if all_segments else 0.0

    full_text = " ".join([w['word'] for w in all_words])

    return {
        'words': all_words,
        'segments': all_segments,
        'full_text': full_text,
        'duration': duration
    }


def transcribe(video_path, progress_callback=None, provider='groq'):
    """
    Main transcription pipeline entrypoint.
    Executes transcription using the configured provider with auto-fallback.
    """
    provider, api_key = resolve_api_keys(provider)
    openai_key = os.getenv("OPENAI_API_KEY")

    def run(key):
        return _run_transcribe(video_path, key, progress_callback, provider)

    return try_with_rate_limit_fallback(provider, api_key, openai_key, run)
