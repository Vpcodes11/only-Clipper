"""
Viral clip detection & cut snapping alignment — supports OpenAI GPT and Groq LLaMA.
Includes speech pause-snapping to prevent cut mid-word.
"""
import json
import re
import os
import time
import logging
from openai import OpenAI
from services.config import (
    AI_API_MAX_RETRIES, AI_API_TIMEOUT_SECONDS,
    LLM_PROVIDERS, resolve_api_keys, try_with_rate_limit_fallback,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a world-class Viral Content Strategist and Video Editor for high-profile podcasts (Joe Rogan, Diary of a CEO, Alex Hormozi style).

Your task is to analyze the podcast transcript and extract the absolute BEST moments that will explode on social media (TikTok, Reels, Shorts).

CRITICAL DIRECTIVES:
1. THE HOOK IS EVERYTHING: Prioritize moments that start with a "Pattern Interrupt" - a shocking statement, a deep question, a counter-intuitive fact, or high-emotion energy.
2. RETENTION FOCUSED: Clips should maintain high tension or high value throughout. No "dead air" or slow build-ups.
3. COMPLETENESS: A clip must be a self-contained story or point. It must have a setup, a middle (climax/insight), and a satisfying resolution or "loopable" ending.
4. SELECTIVE QUALITY: Do not pick boring segments. If only 3 moments are truly engaging, only pick 3. If the whole thing is gold, pick up to 8.

SELECTION CRITERIA:
- INSIGHT: "Aha!" moments where the listener learns something valuable in 60 seconds.
- EMOTION: Moments of raw vulnerability, extreme joy, or intense passion.
- VALUE: Practical, actionable advice or paradigm-shifting perspectives.
- HUMOR: Genuine laugh-out-loud moments or sharp wit.
- CLIFFHANGERS: Moments that make people want to watch the full episode.

SAFETY NOTE: Reject any content that promotes violence, hate speech, harassment, explicit material, or illegal activity. Only select broadly appropriate, platform-safe moments suitable for general audiences.

OUTPUT REQUIREMENTS:
- Duration: 30-75 seconds is the "sweet spot" for virality.
- Timing: Ensure start_time and end_time are extremely precise based on the transcript.
- JSON: Return ONLY valid JSON in the specified format.

JSON FORMAT:
{
    "clips": [
        {
            "title": "CATCHY VIRAL TITLE",
            "hook_caption": "RETENTION HOOK (Text that would be the first thing people see)",
            "start_time": 00.0,
            "end_time": 00.0,
            "virality_score": 9.8,
            "reason": "Why this specific moment will trigger the algorithm",
            "category": "hot_take|insight|emotional|humor|cliffhanger|advice|story|revelation",
            "hashtags": ["#viral", "#podcast", "#hook"]
        }
    ]
}"""


def clean_and_parse_json(text):
    """Extract and parse JSON from LLM response, handling markdown blocks or formatting issues"""
    if not text:
        return None
    text = text.strip()

    # Remove markdown code block wrappers if present (e.g. ```json ... ```)
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: try to find the outer JSON object { ... }
        try:
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                return json.loads(text[start_idx:end_idx + 1])
        except Exception:
            pass
    return None


def snap_to_silence(target_time: float, words: list, direction: str = "nearest",
                     window: float = 2.0, min_gap: float = 0.15) -> float:
    """
    Snaps a target timestamp to the nearest silence boundary in the word list.
    Prevents cuts in the middle of words.
    """
    if not words:
        return target_time

    candidates = []
    for i in range(len(words) - 1):
        gap_start = words[i]['end']
        gap_end = words[i + 1]['start']
        gap_duration = gap_end - gap_start

        # Only consider real silences
        if gap_duration < min_gap:
            continue

        gap_mid = (gap_start + gap_end) / 2

        # Only look within search window
        if abs(gap_mid - target_time) > window:
            continue

        candidates.append({
            'time': gap_start,       # Use start of silence (cleanest cut point)
            'distance': abs(gap_start - target_time),
            'gap': gap_duration
        })

    if not candidates:
        return target_time

    # Sort by distance, then prefer larger gaps as tiebreaker
    candidates.sort(key=lambda c: (c['distance'], -c['gap']))
    best = candidates[0]

    logger.debug("[CutAligner] Snapped %.2fs -> %.2fs (gap: %.2fs, shift: %.2fs)",
                 target_time, best['time'], best['gap'], best['distance'])

    return best['time']


def align_clip_boundaries(clips_info: list, words: list) -> list:
    """
    Applies silence-snapping to start and end times of all clips.
    """
    if not words:
        return clips_info

    aligned = []
    for clip in clips_info:
        original_start = clip['start_time']
        original_end = clip['end_time']

        snapped_start = snap_to_silence(original_start, words, direction='start')
        snapped_end = snap_to_silence(original_end, words, direction='end')

        # Safety: never let the clip become less than 8 seconds
        if snapped_end - snapped_start < 8.0:
            logger.info("Clip too short after snapping, using original bounds.")
            snapped_start = original_start
            snapped_end = original_end

        updated_clip = dict(clip)
        updated_clip['start_time'] = snapped_start
        updated_clip['end_time'] = snapped_end
        aligned.append(updated_clip)

    return aligned


def _run_analyze_transcript(transcript_data, api_key, progress_callback=None, provider='groq'):
    """Send transcript to LLM to find viral-worthy moments with strict validation"""
    config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS['groq'])

    kwargs = {'api_key': api_key}
    if config['base_url']:
        kwargs['base_url'] = config['base_url']
    client = OpenAI(timeout=AI_API_TIMEOUT_SECONDS, max_retries=0, **kwargs)

    if progress_callback:
        progress_callback("Analyzing transcript for viral moments...", 58)

    duration = float(transcript_data.get('duration', 0.0))
    if duration <= 0.0 and transcript_data.get('segments'):
        duration = float(transcript_data['segments'][-1].get('end', 0.0))

    # Group segments into chunks to stay under LLM context limits
    MAX_WORDS_PER_CHUNK = 400
    chunks = []
    current_chunk = []
    current_word_count = 0

    for seg in transcript_data.get('segments', []):
        words_in_seg = len(seg.get('text', '').split())
        if current_word_count + words_in_seg > MAX_WORDS_PER_CHUNK and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [seg]
            current_word_count = words_in_seg
        else:
            current_chunk.append(seg)
            current_word_count += words_in_seg

    if current_chunk:
        chunks.append(current_chunk)

    all_clips = []
    total_chunks = len(chunks)
    failed_chunks = []

    if progress_callback:
        progress_callback(f"Analyzing {total_chunks} sections for viral clips...", 60)

    for i, chunk in enumerate(chunks):
        segments_text = "\n".join([
            f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}"
            for seg in chunk
        ])

        user_prompt = f"""Here is a section of the podcast transcript with timestamps:

<transcript>
{segments_text}
</transcript>

Identify the top 1-3 most engaging, platform-safe moments in this section. Each clip should be 30-90 seconds.
Return ONLY valid JSON.
Remember: reject any content that promotes violence, hate, harassment, explicit material, or illegal activity."""

        create_kwargs = {
            'model': config['llm_model'],
            'messages': [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 1000,
        }

        # Enable JSON object response support if provider supports it
        if provider == 'openai':
            create_kwargs['response_format'] = {"type": "json_object"}

        try:
            response = None
            last_error = None
            for attempt in range(AI_API_MAX_RETRIES + 1):
                try:
                    response = client.chat.completions.create(**create_kwargs)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt >= AI_API_MAX_RETRIES:
                        raise exc
                    delay = min(8, 2 ** attempt)
                    logger.warning("LLM chunk retry provider=%s chunk=%s attempt=%s error=%s", provider, i + 1, attempt + 1, exc)
                    time.sleep(delay)

            if response is None:
                raise RuntimeError(f"LLM analysis failed without response: {last_error}")

            raw_content = response.choices[0].message.content
            result = clean_and_parse_json(raw_content)

            if result and isinstance(result, dict):
                raw_clips = result.get('clips', [])
                if isinstance(raw_clips, list):
                    for clip in raw_clips:
                        if not isinstance(clip, dict):
                            continue

                        # Text fields sanitization
                        title = str(clip.get('title', 'Viral Highlight')).strip()
                        if not title:
                            title = "Viral Highlight"

                        hook_caption = str(clip.get('hook_caption', title)).strip()
                        if not hook_caption:
                            hook_caption = title

                        reason = str(clip.get('reason', 'Strong viewer retention potential.')).strip()
                        category = str(clip.get('category', 'general')).strip()

                        # Hashtags
                        raw_tags = clip.get('hashtags', ['#viral', '#shorts'])
                        if isinstance(raw_tags, list):
                            hashtags = [str(t).strip() for t in raw_tags if t]
                        else:
                            hashtags = ['#viral', '#shorts']

                        # Start and end times
                        try:
                            start_time = float(clip.get('start_time', 0.0))
                        except (ValueError, TypeError):
                            start_time = 0.0

                        try:
                            end_time = float(clip.get('end_time', start_time + 30.0))
                        except (ValueError, TypeError):
                            end_time = start_time + 30.0

                        # Boundaries validation
                        if start_time < 0.0:
                            start_time = 0.0
                        if duration > 0.0 and start_time >= duration:
                            start_time = max(0.0, duration - 30.0)

                        if duration > 0.0 and end_time > duration:
                            end_time = duration

                        if end_time <= start_time:
                            if duration > start_time:
                                end_time = min(duration, start_time + 30.0)
                            else:
                                start_time = max(0.0, end_time - 30.0)

                        # Minimum length safety
                        if (end_time - start_time) < 2.0:
                            if duration > start_time + 10.0:
                                end_time = min(duration, start_time + 30.0)
                            else:
                                start_time = max(0.0, end_time - 30.0)

                        start_time = round(start_time, 1)
                        end_time = round(end_time, 1)

                        # Score
                        try:
                            virality_score = float(clip.get('virality_score', 8.5))
                        except (ValueError, TypeError):
                            virality_score = 8.5
                        virality_score = max(0.0, min(10.0, virality_score))

                        all_clips.append({
                            'title': title,
                            'hook_caption': hook_caption,
                            'start_time': start_time,
                            'end_time': end_time,
                            'virality_score': virality_score,
                            'reason': reason,
                            'category': category,
                            'hashtags': hashtags
                        })
        except Exception as e:
            chunk_num = i + 1
            failed_chunks.append(chunk_num)
            logger.exception("Error analyzing transcript chunk provider=%s chunk=%s/%s error=%s", provider, chunk_num, total_chunks, e)

        if progress_callback:
            pct = 60 + int(((i + 1) / total_chunks) * 10)
            progress_callback(f"Analyzed part {i+1} of {total_chunks}...", pct)

    if failed_chunks:
        logger.warning("Transcript analysis partial failure: %s/%s chunks failed provider=%s failed_chunks=%s",
                       len(failed_chunks), total_chunks, provider, failed_chunks)

    if not all_clips and failed_chunks:
        raise RuntimeError(f"Transcript analysis failed: all {total_chunks} chunks failed for provider={provider}.")

    # Fallback: if no clips found, generate deterministic ones
    if not all_clips:
        logger.warning("No viral moments found. Generating deterministic fallback clips.")
        total_dur = duration if duration > 0.0 else 30.0
        clip_end = min(total_dur, 60.0)
        all_clips.append({
            'title': "Spotlight Moment",
            'hook_caption': "Key highlight from this segment",
            'start_time': 0.0,
            'end_time': round(clip_end, 1),
            'virality_score': 8.0,
            'reason': "Fallback clip generated automatically — no viral moments detected.",
            'category': "general",
            'hashtags': ["#podcast", "#viral", "#spotlight"]
        })

        if total_dur > 120.0:
            mid_start = round(total_dur / 2.0, 1)
            mid_end = min(total_dur, mid_start + 45.0)
            all_clips.append({
                'title': "Key Insight",
                'hook_caption': "Insightful moment from the conversation",
                'start_time': mid_start,
                'end_time': round(mid_end, 1),
                'virality_score': 8.2,
                'reason': "Fallback middle clip generated automatically — no viral moments detected.",
                'category': "general",
                'hashtags': ["#insight", "#viral"]
            })

    # Sort by virality score and return top 8
    all_clips.sort(key=lambda x: x.get('virality_score', 0), reverse=True)
    top_clips = all_clips[:8]

    if progress_callback:
        progress_callback(f"Found {len(top_clips)} viral moments!", 70)

    return top_clips


def analyze_transcript(transcript_data, progress_callback=None, provider='groq'):
    """
    Main entrypoint for transcript analysis.
    Supports auto fallback from Groq to OpenAI on 429 rate limit errors.
    """
    provider, api_key = resolve_api_keys(provider)
    openai_key = os.getenv("OPENAI_API_KEY")

    def run(key):
        return _run_analyze_transcript(transcript_data, key, progress_callback, provider)

    return try_with_rate_limit_fallback(provider, api_key, openai_key, run)
