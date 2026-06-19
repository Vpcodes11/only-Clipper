"""
Viral clip detection & scoring engine — ClipAura Intelligence Layer v2.

Improvements over v1:
- Cross-model judging (generator ≠ judge model) prevents self-validation
- Dynamic context windows (LLM outputs context_start, hook_start, payoff_end)
- Pre-LLM signal enrichment (pacing, pauses, sentiment, intensity in prompts)
- Human psychology scoring (curiosity gap, emotional contagion, identity signal)
- Two-pass judging with different models by default
"""
import json
import re
import os
import time
import logging
from typing import List, Dict, Optional, Callable

from openai import OpenAI
from services.config import (
    AI_API_MAX_RETRIES, AI_API_TIMEOUT_SECONDS,
    LLM_PROVIDERS, resolve_api_keys, try_with_rate_limit_fallback,
)
from services.signals import (
    extract_all_signals, compute_segment_signal_summary,
    format_signals_for_prompt,
)
from services.filters import run_all_filters, generate_filter_report

logger = logging.getLogger(__name__)

# ── Updated Generator Prompt (Dynamic Context Windows + Signal-Aware) ──

GENERATOR_SYSTEM_PROMPT = """You are a world-class Viral Content Strategist for high-profile podcasts.
Your task: analyze a podcast transcript enriched with vocal pacing, pause data, emotional signals,
and speech intensity metadata to extract the 2-3 absolute BEST viral moments PER SECTION.

⬇️  WHAT MAKES A GREAT CLIP (PRIORITIZE THESE):
- Strong opinions / hot takes ("I think X is completely wrong...")
- Contrarian statements ("Most people think X, but actually the opposite is true...")
- Surprising facts or revelations ("Here's what nobody tells you about...")
- Personal failures or vulnerable admissions ("I lost everything because...")
- Personal wins or breakthroughs ("And then I figured out the one thing that changed everything...")
- Emotional moments (anger, excitement, awe, frustration, passion)
- Transformation stories ("Before I realized X, I was Y...")
- High-stakes declarations ("If we don't solve this, X will happen...")
- Curiosity hooks ("What if I told you...", "Imagine if...")
- Punchy one-liners that are quotable on their own

🚫  AVOID (LOWER SCORE OR SKIP):
- Definitions ("X is when...", "Y refers to...")
- Generic explanations without stakes
- Long educational monologues (textbook-style teaching)
- Context-dependent statements that need minutes of setup
- Weak openings with filler ("So, um, like...", "You know, I think...")
- Low-emotion / flat content
- Rambling with no clear point

CRITICAL DIRECTIVES:
1. DYNAMIC CONTEXT: Each clip needs different setup length. Output THREE timestamps:
   - context_start: when the setup/context begins (can be 2-15s before the hook)
   - hook_start: the exact moment of the pattern interrupt / hook
   - payoff_end: when the satisfying conclusion lands

2. THE HOOK: Must be a genuine "Pattern Interrupt" within 3 seconds — shocking statement,
   deep question, emotional revelation, or high-stakes declaration.

3. NARRATIVE SEGMENTATION: Clip should have setup → tension → payoff, but don't force it.
   A punchy hot take doesn't need a long setup — just context_start close to hook_start.

4. PRE-LLM SIGNALS: You are provided with objective signal data (pacing shifts, emotional peaks,
   viral heat markers, arousal levels). Use these to inform your scoring — do NOT hallucinate
   signal values that contradict the provided data.

5. CATEGORIZE CORRECTLY based on the clip's primary appeal:
   - hot_take: controversial opinion
   - insight: surprising truth or realization
   - emotional: vulnerable, angry, excited, moving
   - humor: funny moment
   - cliffhanger: setup with unresolved tension
   - advice: actionable wisdom
   - story: personal narrative
   - revelation: revealing something hidden

SCORING GUIDELINES (rate 1-10):
- hook_strength: Can someone immediately tell this is interesting? (9+ = "You won't BELIEVE...")
- emotional_impact: Does the speaker feel something strongly? (9+ = anger, awe, passion)
- curiosity_gap: Does it make you NEED to know what happens? (9+ = setups that demand resolution)
- shareability: Would someone send this to a friend? (9+ = quotable, relatable, surprising)
- identity_signal: Would sharing this make someone look smart? (9+ = deep insight)
- emotional_contagion: Does the emotion jump through the screen? (9+ = palpable feeling)
- narrative_completeness: Is there a clear arc? (Lower is OK for punchy hot takes!)
- payoff_satisfaction: Does it deliver? (9+ = punchline or mic-drop moment)
- peak_end_quality: Does it end strong? (9+ = memorable final line)

JSON FORMAT:
{
    "clips": [
        {
            "title": "CATCHY VIRAL TITLE",
            "hook_caption": "RETENTION HOOK TEXT",
            "context_start": 00.0,
            "hook_start": 00.0,
            "payoff_end": 00.0,
            "setup_description": "What context is established",
            "payoff_description": "How the moment resolves",
            "scores": {
                "hook_strength": 9.0,
                "emotional_impact": 8.5,
                "narrative_completeness": 9.5,
                "curiosity_gap": 8.0,
                "emotional_contagion": 8.0,
                "identity_signal": 8.5,
                "payoff_satisfaction": 9.0,
                "peak_end_quality": 8.0,
                "shareability": 9.5
            },
            "reason": "Why this specific moment will trigger retention and shares",
            "category": "hot_take|insight|emotional|humor|cliffhanger|advice|story|revelation",
            "hashtags": ["#viral", "#podcast"]
        }
    ]
}"""

# ── Updated Judge Prompt (Cross-Model Validation) ──

JUDGE_SYSTEM_PROMPT = """You are the FINAL JUDGE for a premium viral clipping agency.
Your job is DIFFERENT from the clip generator — you are a separate evaluator providing
external validation. Review candidate clips and select only the absolute best.

⬇️  PREFER CLIPS WITH:
- Strong opinions, hot takes, contrarian statements
- Personal stories with emotional stakes
- Surprising revelations or facts
- Punchy one-liners that are quotable
- Curiosity hooks that demand completion
- Transformation arcs or lessons learned
- High-arousal emotions (anger, excitement, awe, passion)

🚫  REJECT OR DOWNGRADE:
- Definitions, textbook explanations, generic education
- Rambling with no clear point or payoff
- Flat, low-emotion content
- Openings with filler ("So, um, like, you know...")
- Content that requires minutes of prior context
- Trail-off endings that go nowhere

CRITICAL DIRECTIVES:
1. STANDALONE COMPLETENESS: Can a stranger understand this without any prior context? 
   If not → REJECT.

2. HOOK VALIDATION: Within 3 seconds, is there a genuine pattern interrupt? 
   No weak "um, so, like, you know" openings. Weak hook → REJECT.

3. PAYOFF DETECTION: Does the clip deliver on its promise? Does it END on something 
   satisfying — a punchline, revelation, emotional climax, or clear takeaway?
   Trail-off ending → REJECT.

4. CONTEXT WINDOW AUDIT: Is the context_start → hook_start gap enough to set up 
   without being boring? Too short (< 2s) or too long (> 15s with no tension) → FLAG.

5. HUMAN SHAREABILITY TEST: "Would a real person, scrolling at midnight, stop and
   watch this, then feel compelled to send it to someone?" 
   No → REJECT.

6. EMOTIONAL CONTAGION: Is the emotion high-arousal (awe, anger, excitement, amusement)?
   Low-arousal (calm, sad, peaceful) clips are harder to make viral. Score accordingly.

7. SIGNAL CORRELATION: Cross-reference the pre-LLM signal data provided. If the generator's
   scores contradict the objective signals (e.g., claiming high arousal when signals show flat),
   DOWNGRADE the score.

8. VIRAL HEAT: The "viral heat" signal data shows detected markers (contrarian, strong_opinion,
   personal_story, curiosity). Prefer clips with high viral heat values.

You will receive candidate clips with pre-LLM signal data. 
Filter and return up to 8 of the best in valid JSON.

JSON FORMAT:
{
    "clips": [
        {
            "title": "APPROVED VIRAL TITLE",
            "hook_caption": "VALIDATED HOOK TEXT",
            "context_start": 00.0,
            "hook_start": 00.0,
            "payoff_end": 00.0,
            "virality_score": 9.8,
            "reason": "Judge's reasoning for selection",
            "category": "category",
            "hashtags": ["#viral"],
            "judge_notes": {
                "standalone_pass": true,
                "hook_strength_rating": 9,
                "payoff_quality_rating": 8,
                "human_shareability_rating": 9,
                "signal_correlation_rating": 8
            }
        }
    ]
}"""


# ── Human Psychology Scoring (Post-LLM computation layer) ──

def compute_psychology_scores(clip: dict, signals: dict, words: List[dict]) -> dict:
    """
    Compute human psychology dimensions that the LLM can't reliably estimate.
    These are data-driven scores based on the actual transcript signals.

    V2 improvements:
    - Broader curiosity gap detection (not just "?" — also curiosity-triggering words)
    - Identity signal scans the entire clip, not just last 3 seconds
    - Hot take detection from word patterns
    - Better payoff detection via ending analysis
    """
    start = clip.get("hook_start", clip.get("start_time", 0))
    end = clip.get("payoff_end", clip.get("end_time", 0))

    # Get window signals
    sentiment_data = signals.get("sentiment", {}).get("segments", [])
    window_sent = [s for s in sentiment_data if start - 1 <= s.get("start", 0) <= end + 1]

    # Get all words in clip window for richer analysis
    clip_words = [w for w in words if start <= w.get("start", 0) <= end]
    clip_text = " ".join(w.get("word", "") for w in clip_words).lower()

    # ── Curiosity Gap Detection (V2) ──
    hook_words = [w for w in clip_words if w.get("start", 0) <= start + 5.0]
    hook_text = " ".join(w.get("word", "") for w in hook_words).lower()

    # Method 1: Literal question marks
    has_question = any("?" in w.get("word", "") for w in hook_words)
    question_pos = None
    if has_question:
        for w in hook_words:
            if "?" in w.get("word", ""):
                question_pos = w.get("end", 0)
                break

    curiosity_score = 0.0
    if has_question and question_pos:
        remaining_dur = end - question_pos
        if remaining_dur > 15:
            curiosity_score = min(1.0, remaining_dur / 45.0)
        elif remaining_dur > 5:
            curiosity_score = 0.5

    # Method 2: Curiosity-triggering phrases (even without "?")
    CURIOSITY_PHRASES = [
        "imagine", "what if", "here's the thing", "the secret", "nobody",
        "what happens when", "the problem is", "the truth is", "here's what",
        "you won't believe", "wait until", "have you ever", "the reason",
        "this is why", "that's why", "what most people don't", "the difference",
        "here's why", "let me tell you", "here's the problem",
        "think about this", "consider this", "this is going to blow your mind",
    ]
    curiosity_phrase_count = sum(1 for p in CURIOSITY_PHRASES if p in hook_text)
    if curiosity_phrase_count > 0 and curiosity_score < 0.5:
        curiosity_score = max(curiosity_score, 0.3 * min(curiosity_phrase_count, 3))

    # ── Emotional Contagion (arousal level) ──
    arousal_values = [s.get("arousal", 0) for s in window_sent]
    max_arousal = max(arousal_values) if arousal_values else 0
    emotional_contagion_score = min(1.0, max_arousal * 20)

    # ── Payoff Satisfaction (V2) — check ending region ──
    if len(arousal_values) >= 2:
        end_arousal = arousal_values[-3:] if len(arousal_values) >= 3 else arousal_values
        payoff_satisfaction = sum(end_arousal) / len(end_arousal) * 15
    else:
        payoff_satisfaction = 0.5

    # Boost payoff if the ending has resolution markers
    end_words = [w for w in clip_words if w.get("start", 0) >= end - 5.0]
    end_text = " ".join(w.get("word", "") for w in end_words).lower()
    RESOLUTION_BOOSTERS = [
        "that's why", "and that's", "so that's", "the point is", "bottom line",
        "that's the", "it changed", "never looked back", "the end",
        "that's the truth", "that's how", "and that changed",
    ]
    if any(p in end_text for p in RESOLUTION_BOOSTERS):
        payoff_satisfaction = max(payoff_satisfaction, 8.0)

    # ── Identity Signaling (V2) — scan entire clip ──
    WISDOM_CLUSTERS = [
        "never", "always", "the truth", "lesson", "realized", "understood",
        "changed", "secret", "nobody tells you", "most people", "the key",
        "difference between", "actually", "in reality", "what they don't",
        "the thing is", "here's the thing", "i learned", "i realized",
        "i discovered", "the problem", "the answer", "the solution",
        "the difference", "the reason", "that's why", "this is why",
        "the moment i", "it hit me", "it clicked", "i figured out",
    ]
    identity_signal_count = sum(1 for s in WISDOM_CLUSTERS if s in clip_text)
    identity_score = min(1.0, identity_signal_count * 0.2)

    # ── Hot Take Detection (New) ──
    HOT_TAKE_MARKERS = [
        "but here's", "actually", "the opposite", "contrary", "most people think",
        "everyone thinks", "nobody talks about", "unpopular opinion", "hot take",
        "i used to think", "i changed my mind", "i was wrong", "the truth is",
        "here's the thing", "what nobody tells you", "i hate", "i love",
        "the best", "the worst", "controversial", "hear me out",
        "here's what most people", "the reality is", "believe it or not",
        "surprisingly", "it turns out", "turns out",
    ]
    hot_take_count = sum(1 for m in HOT_TAKE_MARKERS if m in hook_text)
    hot_take_score = min(1.0, hot_take_count * 0.5)

    # ── Peak-end quality ──
    peak_end = 0.0
    if len(arousal_values) >= 2:
        last_arousal = arousal_values[-1]
        max_arousal_in_clip = max(arousal_values)
        if max_arousal_in_clip > 0:
            peak_end = last_arousal / max_arousal_in_clip

    return {
        "curiosity_gap": round(curiosity_score, 3),
        "emotional_contagion": round(emotional_contagion_score, 3),
        "payoff_satisfaction": round(payoff_satisfaction, 3),
        "identity_signal": round(identity_score, 3),
        "peak_end_quality": round(peak_end, 3),
        "hot_take_score": round(hot_take_score, 3),
    }


# ── JSON Parsing Helpers ──

def clean_and_parse_json(text):
    """Extract and parse JSON from LLM response"""
    if not text:
        return None
    text = text.strip()
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                return json.loads(text[start_idx:end_idx + 1])
        except Exception:
            pass
    return None


# ── Silence Snapping ──

def snap_to_silence(target_time: float, words: list, window: float = 2.0,
                     min_gap: float = 0.15) -> float:
    """Snaps a timestamp to nearest silence boundary between words."""
    if not words:
        return target_time
    candidates = []
    for i in range(len(words) - 1):
        gap_start = words[i]['end']
        gap_end = words[i + 1]['start']
        gap_duration = gap_end - gap_start
        if gap_duration < min_gap:
            continue
        if abs(gap_start - target_time) > window:
            continue
        candidates.append({
            'time': gap_start,
            'distance': abs(gap_start - target_time),
            'gap': gap_duration
        })
    if not candidates:
        return target_time
    candidates.sort(key=lambda c: (c['distance'], -c['gap']))
    return candidates[0]['time']


def align_clip_boundaries(clips_info: list, words: list) -> list:
    """Applies silence-snapping to all clip boundaries.
    Guarantees context_start <= hook_start <= payoff_end after snapping."""
    if not words:
        return clips_info
    aligned = []
    for clip in clips_info:
        orig_context = clip.get('context_start', clip.get('start_time', 0))
        orig_hook = clip.get('hook_start', clip.get('start_time', 0))
        orig_end = clip.get('payoff_end', clip.get('end_time', 0))

        snapped_context = snap_to_silence(orig_context, words)
        snapped_hook = snap_to_silence(orig_hook, words)
        snapped_end = snap_to_silence(orig_end, words)

        # Ensure ordering: context <= hook <= payoff_end
        snapped_context = min(snapped_context, snapped_hook)
        snapped_hook = max(snapped_hook, snapped_context)
        snapped_end = max(snapped_end, snapped_hook)

        # Guard against snapping that makes clip too short — revert to originals
        if snapped_end - snapped_context < 8.0:
            updated = dict(clip)
            updated['context_start'] = orig_context
            updated['hook_start'] = orig_hook
            updated['payoff_end'] = orig_end
            updated['start_time'] = orig_context
            updated['end_time'] = orig_end
            aligned.append(updated)
            continue

        updated = dict(clip)
        updated['context_start'] = snapped_context
        updated['hook_start'] = snapped_hook
        updated['payoff_end'] = snapped_end
        updated['start_time'] = snapped_context
        updated['end_time'] = snapped_end
        aligned.append(updated)
    return aligned


# ── Transcript Enrichment ──

def generate_multimodal_transcript(words, segments, signals=None):
    """Injects pauses, pacing, and signal data into transcript segments."""
    if not words:
        return [{'start': seg.get('start', 0), 'end': seg.get('end', 0),
                 'text': seg.get('text', '')} for seg in segments]

    enriched = []
    word_idx = 0
    num_words = len(words)

    for i, seg in enumerate(segments):
        seg_start = seg.get('start', 0)
        seg_end = seg.get('end', 0)
        seg_text = seg.get('text', '')

        seg_word_count = 0
        pauses = []

        while word_idx < num_words and words[word_idx]['start'] < seg_end:
            w = words[word_idx]
            if w['start'] >= seg_start:
                seg_word_count += 1
            if word_idx < num_words - 1:
                next_w = words[word_idx + 1]
                gap = next_w['start'] - w['end']
                if gap >= 1.0:
                    pauses.append(gap)
            word_idx += 1

        dur = seg_end - seg_start
        wpm = (seg_word_count / dur) * 60 if dur > 0 else 0
        pacing = "normal"
        if wpm > 180:
            pacing = "fast"
        elif wpm < 110:
            pacing = "slow"

        # Add signal data if available
        signal_meta = ""
        if signals:
            sent_segs = signals.get("sentiment", {}).get("segments", [])
            if i < len(sent_segs):
                s = sent_segs[i]
                signal_meta = (f"[Sentiment:{s.get('sentiment', 0):.2f} "
                               f"Arousal:{s.get('arousal', 0):.3f} "
                               f"Curiosity:{s.get('curiosity', 0):.3f}] ")

        pause_str = f" [Pauses: {len(pauses)} >1s]" if pauses else ""
        meta_str = f"[Pacing: {pacing} WPM:{wpm:.0f}]{pause_str}"

        enriched.append({
            'start': seg_start,
            'end': seg_end,
            'text': f"{signal_meta}{meta_str} {seg_text}"
        })

    return enriched


# ── Deduplication ──

def get_overlap(start1, end1, start2, end2):
    overlap = max(0, min(end1, end2) - max(start1, start2))
    dur1 = end1 - start1
    dur2 = end2 - start2
    if dur1 <= 0 or dur2 <= 0:
        return 0
    return max(overlap / dur1, overlap / dur2)


def semantic_deduplication(clips, threshold=0.4):
    """Deduplicate clips with category diversity.
    Ensures variety: limits same-category clips and prefers diverse categories.
    """
    clips.sort(key=lambda x: x.get('composite_score', 0), reverse=True)
    kept = []
    category_count = {}

    for c in clips:
        overlap = False
        for k in kept:
            c_start = c.get('context_start', c.get('start_time', 0))
            c_end = c.get('payoff_end', c.get('end_time', 0))
            k_start = k.get('context_start', k.get('start_time', 0))
            k_end = k.get('payoff_end', k.get('end_time', 0))
            if get_overlap(c_start, c_end, k_start, k_end) > threshold:
                overlap = True
                break

        if overlap:
            continue

        # Category diversity: max 3 clips per category
        cat = c.get('category', 'general')
        if category_count.get(cat, 0) >= 3:
            continue

        kept.append(c)
        category_count[cat] = category_count.get(cat, 0) + 1

    return kept


# ── Cross-Model Client Setup ──

def _get_client(provider: str, api_key: str) -> OpenAI:
    """Create OpenAI-compatible client for a specific provider."""
    config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS['groq'])
    kwargs = {'api_key': api_key}
    if config['base_url']:
        kwargs['base_url'] = config['base_url']
    return OpenAI(timeout=AI_API_TIMEOUT_SECONDS, max_retries=0, **kwargs)


def _get_model_name(provider: str) -> str:
    """Get the LLM model name for a provider."""
    config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS['groq'])
    return config['llm_model']


# ── Viral Heat Computation ──

def _compute_viral_heat_for_window(viral_signals: dict, clip: dict, words: List[dict]) -> dict:
    """
    Compute viral quality heat for a specific clip window from pre-computed viral signals.
    Adds transcript-level checks for personal narrative, contrarian content, and opinion density.
    """
    start = clip.get("hook_start", clip.get("start_time", 0))
    end = clip.get("payoff_end", clip.get("end_time", 0))

    # Get viral segments in this window
    viral_segs = viral_signals.get("segment_viral_scores", [])
    window_heat = [s["viral_heat"] for s in viral_segs
                   if start <= s.get("start", 0) <= end]

    avg_heat = sum(window_heat) / max(len(window_heat), 1) if window_heat else 0

    # Additional transcript-level checks for this window
    clip_words = [w for w in words if start <= w.get("start", 0) <= end]
    clip_text = " ".join(w.get("word", "") for w in clip_words).lower()

    # Check hook region (first 5s) for strong opinion/contrarian/personal markers
    hook_words = [w for w in clip_words if w.get("start", 0) <= start + 5.0]
    hook_text = " ".join(w.get("word", "") for w in hook_words).lower()

    hook_quality = 0
    if any(p in hook_text for p in ["i think", "i believe", "i hate", "i love",
                                     "the truth", "actually", "nobody", "everyone",
                                     "the best", "the worst", "here's", "what if",
                                     "imagine", "secret", "never", "always",
                                     "most people", "nobody tells"]):
        hook_quality = 1.0
    elif any("?" in w.get("word", "") for w in hook_words):
        hook_quality = 0.8

    # Check for punchy ending (last 5s — quotable one-liner potential)
    end_words = [w for w in clip_words if w.get("start", 0) >= end - 5.0]
    end_text = " ".join(w.get("word", "") for w in end_words).lower()
    ending_quality = 0
    if any(p in end_text for p in [".", "!", "?", "that's why", "that's how",
                                    "and that's", "that changed", "never looked back",
                                    "the end", "period"]):
        # Has terminal punctuation — suggests complete thought
        ending_quality = 0.5
    if any(p in end_text for p in ["that's the truth", "bottom line", "period",
                                    "end of story", "that's it", "full stop"]):
        ending_quality = 1.0  # Mic-drop ending

    # Personal narrative detection in clip
    personal_pronoun_density = sum(1 for w in clip_words
                                   if w.get("word", "").lower() in {"i", "me", "my",
                                                                     "we", "our"})
    personal_ratio = personal_pronoun_density / max(len(clip_words), 1)

    # Final viral heat score (0-10)
    viral_heat = (
        avg_heat * 0.4 +
        hook_quality * 3.0 +
        ending_quality * 1.5 +
        min(personal_ratio * 10, 2.0)     # Personal stories boost virality
    )

    return {
        "viral_heat": round(min(viral_heat, 10.0), 2),
        "avg_signal_heat": round(avg_heat, 2),
        "hook_quality": round(hook_quality, 2),
        "ending_quality": round(ending_quality, 2),
        "personal_ratio": round(personal_ratio, 3),
    }


# ── Main Analysis Pipeline ──

def _run_analyze_transcript(transcript_data, api_key, progress_callback=None, provider='groq'):
    """
    Full analysis pipeline with cross-model judging and signal enrichment.
    """
    config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS['groq'])

    kwargs = {'api_key': api_key}
    if config['base_url']:
        kwargs['base_url'] = config['base_url']
    client = OpenAI(timeout=AI_API_TIMEOUT_SECONDS, max_retries=0, **kwargs)
    gen_model = config['llm_model']

    duration = float(transcript_data.get('duration', 0.0))
    if duration <= 0.0 and transcript_data.get('segments'):
        duration = float(transcript_data['segments'][-1].get('end', 0.0))

    words = transcript_data.get('words', [])
    segments = transcript_data.get('segments', [])

    # ── Step 1: Pre-LLM Signal Extraction ──
    if progress_callback:
        progress_callback("Computing objective audio/textual signals...", 52)

    all_signals = extract_all_signals(words, segments)
    logger.info("Pre-LLM signals computed: pacing_variance=%s, emotional_peaks=%d, dead_air=%d",
                all_signals["pacing"].get("pacing_variance", 0),
                len(all_signals["sentiment"].get("emotional_peaks", [])),
                len(all_signals["pauses"].get("dead_air_segments", [])))

    # ── Step 2: Enrich Transcript with Multimodal + Signal Data ──
    if progress_callback:
        progress_callback("Enriching transcript with signal metadata...", 56)

    enriched_segments = generate_multimodal_transcript(words, segments, all_signals)

    from services.segmentation import segment_transcript_semantically
    
    # ── Step 3: Semantic Scene Segmentation ──
    chunks = segment_transcript_semantically(enriched_segments, max_words=300)
    total_chunks = len(chunks)
    all_candidates = []

    if progress_callback:
        progress_callback(f"Pass 1: Generating candidates ({gen_model}) across {total_chunks} sections...", 58)

    for i, chunk in enumerate(chunks):
        if i > 0 and provider == 'groq':
            # Sleep to respect Groq's 6000 TPM limit on free tiers
            time.sleep(15)

        chunk_start = chunk[0]['start']
        chunk_end = chunk[-1]['end']

        segments_text = "\n".join([
            f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}"
            for seg in chunk
        ])

        # Include signal metadata for this chunk
        signal_summary = format_signals_for_prompt(all_signals, chunk_start, chunk_end)

        user_prompt = f"""Here is a section of the podcast transcript with timestamps, vocal metadata, 
and pre-computed signal data:

<signal_data>
{signal_summary}
</signal_data>

<transcript>
{segments_text}
</transcript>

Identify 2-3 of the most engaging, platform-safe moments in this section. 
For each clip, provide context_start, hook_start, and payoff_end timestamps.
Use the signal data to inform your scoring — don't contradict it.
Return ONLY valid JSON."""

        create_kwargs = {
            'model': gen_model,
            'messages': [
                {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 1000,
        }
        if provider == 'openai':
            create_kwargs['response_format'] = {"type": "json_object"}

        try:
            response = None
            for attempt in range(AI_API_MAX_RETRIES + 1):
                try:
                    response = client.chat.completions.create(**create_kwargs)
                    break
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if attempt >= AI_API_MAX_RETRIES:
                        # After exhausting local retries, let rate limits propagate
                        # so try_with_rate_limit_fallback can swap providers.
                        if "429" in err_msg or "rate limit" in err_msg:
                            raise
                        raise exc
                    # If rate limited, sleep longer
                    delay = 35 if "429" in err_msg or "rate limit" in err_msg else min(8, 2 ** attempt)
                    logger.warning("Chunk %d LLM call attempt %d failed: %s. Retrying in %ds.",
                                   i + 1, attempt + 1, err_msg[:100], delay)
                    time.sleep(delay)

            if response:
                raw_content = response.choices[0].message.content
                result = clean_and_parse_json(raw_content)
                if result and isinstance(result, dict):
                    raw_clips = result.get('clips', [])
                    for clip in raw_clips:
                        if not isinstance(clip, dict):
                            continue

                        # Extract dynamic context windows
                        context_start = float(clip.get('context_start', clip.get('start_time', 0)))
                        hook_start = float(clip.get('hook_start', clip.get('start_time', 0)))
                        payoff_end = float(clip.get('payoff_end', clip.get('end_time', 0)))

                        # Validate: context must be before hook, hook before payoff
                        context_start = min(context_start, hook_start)
                        if payoff_end <= hook_start:
                            payoff_end = hook_start + 30.0

                        clip['context_start'] = max(0.0, context_start)
                        clip['hook_start'] = hook_start
                        clip['payoff_end'] = min(payoff_end, duration)
                        
                        # Normalize for downstream filters which expect start_time and end_time
                        clip['start_time'] = clip['context_start']
                        clip['end_time'] = clip['payoff_end']

                        scores = clip.get('scores', {})

                        # LLM scores scaled to 0-10
                        hook_strength = float(scores.get('hook_strength', scores.get('hook_score', 5.0)))
                        emotional_impact = float(scores.get('emotional_impact', scores.get('emotion_score', 5.0)))
                        narrative_completeness = float(scores.get('narrative_completeness', scores.get('story_score', 5.0)))
                        curiosity_llm = float(scores.get('curiosity_gap', scores.get('curiosity_score', 5.0)))
                        contagion_llm = float(scores.get('emotional_contagion', 5.0))
                        identity_llm = float(scores.get('identity_signal', 5.0))
                        payoff_llm = float(scores.get('payoff_satisfaction', 5.0))
                        peak_end_llm = float(scores.get('peak_end_quality', 5.0))
                        shareability = float(scores.get('shareability', scores.get('shareability_score', 5.0)))

                        # Compute human psychology scores from actual signals
                        psych = compute_psychology_scores(clip, all_signals, words)

                        # ── V2: Reweighted LLM composite ──
                        # Reduces narrative_completeness (penalizes safe educational monologues)
                        # Boosts emotional_contagion, identity_signal, curiosity_gap (drives virality)
                        V2_WEIGHTS = {
                            'hook_strength': 2.0,           # Hook is everything
                            'shareability': 1.8,            # Ultimate viral metric
                            'curiosity_gap': 1.5,           # Drives retention
                            'emotional_contagion': 1.3,     # Emotion drives shares
                            'identity_signal': 1.2,         # Sharing to look smart
                            'emotional_impact': 1.2,        # Emotional resonance
                            'payoff_satisfaction': 1.0,     # Slightly reduced
                            'narrative_completeness': 0.7,  # REDUCED — penalizes boring explanations
                            'peak_end_quality': 0.9,        # Slightly reduced
                        }
                        v2_sum = sum(V2_WEIGHTS.values())  # = 11.6

                        llm_composite_v2 = (
                            (hook_strength * V2_WEIGHTS['hook_strength']) +
                            (emotional_impact * V2_WEIGHTS['emotional_impact']) +
                            (narrative_completeness * V2_WEIGHTS['narrative_completeness']) +
                            (curiosity_llm * V2_WEIGHTS['curiosity_gap']) +
                            (contagion_llm * V2_WEIGHTS['emotional_contagion']) +
                            (identity_llm * V2_WEIGHTS['identity_signal']) +
                            (payoff_llm * V2_WEIGHTS['payoff_satisfaction']) +
                            (peak_end_llm * V2_WEIGHTS['peak_end_quality']) +
                            (shareability * V2_WEIGHTS['shareability'])
                        ) / v2_sum

                        # ── V2: Improved psychology composite from signals ──
                        # Includes better curiosity detection, identity signal, and hot take detection
                        viral_signals = all_signals.get("viral", {})
                        heat = _compute_viral_heat_for_window(viral_signals, clip, words)

                        psych_composite_v2 = (
                            psych['curiosity_gap'] * 2.0 +
                            psych['emotional_contagion'] * 1.5 +
                            psych['payoff_satisfaction'] * 1.5 +
                            psych['identity_signal'] * 1.5 +       # Increased weight
                            psych['peak_end_quality'] * 1.0 +
                            heat['viral_heat'] * 2.0               # New: viral quality boost
                        ) * 10 / 9.5  # Scale to ~0-10

                        # ── V2: Three-layer composite ──
                        # 50% LLM (reweighted), 30% psychology (improved), 20% viral heat (new)
                        composite = (
                            llm_composite_v2 * 0.50 +
                            psych_composite_v2 * 0.30 +
                            heat['viral_heat'] * 2.0               # Viral heat as direct boost (0-20 scale → 0-10)
                        )

                        clip['composite_score'] = round(composite, 2)
                        clip['llm_composite'] = round(llm_composite_v2, 2)
                        clip['psych_composite'] = round(psych_composite_v2, 2)
                        clip['viral_heat_score'] = round(heat['viral_heat'], 2)
                        clip['viral_signals'] = heat
                        clip['psychology_scores'] = psych

                        all_candidates.append(clip)

        except Exception as e:
            err_msg = str(e).lower()
            # Re-raise rate limit errors so try_with_rate_limit_fallback can swap providers.
            if "429" in err_msg or "rate limit" in err_msg:
                logger.warning("Rate limit on chunk %d, propagating for provider fallback.", i + 1)
                raise
            logger.exception("Pass 1 non-fatal error on chunk %s: %s", i + 1, e)

        if progress_callback:
            pct = 58 + int(((i + 1) / total_chunks) * 7)
            progress_callback(f"Analyzed part {i+1}/{total_chunks}", pct)

    if not all_candidates:
        raise RuntimeError("Transcript analysis failed: no candidates generated.")

    # ── Step 4: Semantic Deduplication ──
    deduped = semantic_deduplication(all_candidates)

    # ── Step 5: Rule-Based Quality Filtering ──
    if progress_callback:
        progress_callback("Running rule-based quality filters...", 65)

    filtered_candidates = []
    filter_reports = {}
    for c in deduped:
        c_start = c.get('hook_start', c.get('start_time', 0))
        c_end = c.get('payoff_end', c.get('end_time', 0))
        filter_clip = {'start_time': c_start, 'end_time': c_end}

        # Compute window-specific signals
        window_signals = compute_segment_signal_summary(segments, words, c_start, c_end)

        filter_result = run_all_filters(
            filter_clip, words, segments, window_signals,
            accepted_clips=filtered_candidates
        )

        if filter_result["passed"]:
            filtered_candidates.append(c)

        filter_reports[f"{c_start:.1f}-{c_end:.1f}"] = filter_result

    logger.info("Quality filters: %d/%d candidates passed (%d rejected)",
                len(filtered_candidates), len(deduped),
                len(deduped) - len(filtered_candidates))

    top_candidates = filtered_candidates[:15]

    # ── Step 6: Cross-Model Judging ──
    if progress_callback:
        progress_callback("Pass 2: Cross-model judging...", 66)

    # Determine judge provider: use the OPPOSITE of the generator
    judge_provider = 'openai' if provider == 'groq' else 'groq'

    try:
        judge_config = LLM_PROVIDERS.get(judge_provider, LLM_PROVIDERS['openai'])
        openai_key = os.getenv("OPENAI_API_KEY")
        groq_key = os.getenv("GROQ_API_KEY")

        if judge_provider == 'openai' and openai_key:
            judge_client, judge_model = _get_client('openai', openai_key), judge_config['llm_model']
        elif judge_provider == 'groq' and groq_key:
            judge_client, judge_model = _get_client('groq', groq_key), judge_config['llm_model']
        else:
            # Fallback: use same provider but different temperature
            judge_client, judge_model = client, gen_model
            judge_provider = provider
            logger.warning("Cannot use different judge model (missing API key). Using same model with lower temp.")

        logger.info("Cross-model judge: generator=%s/%s, judge=%s/%s",
                     provider, gen_model, judge_provider, judge_model)

        # Prepare candidate payload with signal data
        judge_candidates = []
        for c in top_candidates:
            c_start = c.get('hook_start', c.get('start_time', 0))
            c_end = c.get('payoff_end', c.get('end_time', 0))
            signal_summary = format_signals_for_prompt(all_signals, c_start, c_end)
            judge_candidates.append({
                **{k: v for k, v in c.items() if k not in ('psychology_scores',)},
                "signal_data": signal_summary,
            })

        judge_prompt = f"""Review these {len(judge_candidates)} candidate clips against the criteria.
For each, the generator provided scores and reasoning, PLUS objective signal data.
Cross-reference the scores against the signals. Reject contradictions.

<candidates>
{json.dumps(judge_candidates, indent=2)}
</candidates>"""

        judge_kwargs = {
            'model': judge_model,
            'messages': [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": judge_prompt}
            ],
            'temperature': 0.4 if judge_provider != provider else 0.3,
            'max_tokens': 2500,
        }
        if judge_provider == 'openai':
            judge_kwargs['response_format'] = {"type": "json_object"}

        final_clips = []
        try:
            response = None
            for attempt in range(AI_API_MAX_RETRIES + 1):
                try:
                    response = judge_client.chat.completions.create(**judge_kwargs)
                    break
                except Exception as exc:
                    if attempt >= AI_API_MAX_RETRIES:
                        raise exc
                    time.sleep(min(8, 2 ** attempt))

            if response:
                raw_content = response.choices[0].message.content
                result = clean_and_parse_json(raw_content)
                if result and isinstance(result, dict):
                    raw_clips = result.get('clips', [])
                    for clip in raw_clips:
                        if not isinstance(clip, dict):
                            continue

                        title = str(clip.get('title', 'Viral Highlight')).strip() or "Viral Highlight"
                        hook_caption = str(clip.get('hook_caption', title)).strip() or title
                        reason = str(clip.get('reason', '')).strip()
                        category = str(clip.get('category', 'general')).strip()

                        raw_tags = clip.get('hashtags', ['#viral', '#shorts'])
                        hashtags = [str(t).strip() for t in raw_tags if t] if isinstance(raw_tags, list) else ['#viral']

                        context_start = float(clip.get('context_start', clip.get('start_time', 0)))
                        hook_start = float(clip.get('hook_start', clip.get('start_time', 0)))
                        payoff_end = float(clip.get('payoff_end', clip.get('end_time', 0)))

                        if duration > 0.0 and payoff_end > duration:
                            payoff_end = duration
                        if payoff_end <= hook_start:
                            payoff_end = hook_start + 30.0

                        try:
                            virality_score = float(clip.get('virality_score', 8.5))
                        except (ValueError, TypeError):
                            virality_score = 8.5
                        virality_score = max(0.0, min(10.0, virality_score))

                        judge_notes = clip.get('judge_notes', {})

                        final_clips.append({
                            'title': title,
                            'hook_caption': hook_caption,
                            'context_start': round(context_start, 1),
                            'hook_start': round(hook_start, 1),
                            'payoff_end': round(payoff_end, 1),
                            'start_time': round(context_start, 1),
                            'end_time': round(payoff_end, 1),
                            'virality_score': round(virality_score, 1),
                            'reason': reason,
                            'category': category,
                            'hashtags': hashtags,
                            'judge_notes': judge_notes,
                            'judge_provider': judge_provider,
                            'judge_model': judge_model,
                            'generator_provider': provider,
                            'generator_model': gen_model,
                        })
        except Exception as e:
            logger.exception("Pass 2 (cross-model judge) error: %s", e)

    except Exception as e:
        logger.exception("Cross-model judge setup failed: %s", e)
        final_clips = []

    # ── Fallback: If judge failed, use Pass 1 results ──
    if not final_clips:
        logger.warning("Judge produced no clips. Using top Pass 1 candidates as fallback.")
        for c in top_candidates[:8]:
            final_clips.append({
                'title': c.get('title', 'Viral Highlight'),
                'hook_caption': c.get('hook_caption', c.get('title', '')),
                'context_start': round(c.get('context_start', c.get('start_time', 0)), 1),
                'hook_start': round(c.get('hook_start', c.get('start_time', 0)), 1),
                'payoff_end': round(c.get('payoff_end', c.get('end_time', 0)), 1),
                'start_time': round(c.get('context_start', c.get('start_time', 0)), 1),
                'end_time': round(c.get('payoff_end', c.get('end_time', 0)), 1),
                'virality_score': c.get('composite_score', 8.5),
                'reason': c.get('reason', ''),
                'category': c.get('category', 'general'),
                'hashtags': c.get('hashtags', ['#viral']),
                'judge_notes': {'fallback': True},
                'judge_provider': 'none',
                'generator_provider': provider,
                'generator_model': gen_model,
            })

    final_clips.sort(key=lambda x: x.get('virality_score', 0), reverse=True)
    top_clips = final_clips[:8]

    if progress_callback:
        progress_callback(f"Found {len(top_clips)} viral-quality moments!", 70)

    return top_clips


def analyze_transcript(transcript_data, progress_callback=None, provider='groq'):
    """
    Main entrypoint for transcript analysis with cross-model judging.
    Auto-falls back between Groq and OpenAI on rate limits.
    """
    provider, api_key = resolve_api_keys(provider)
    openai_key = os.getenv("OPENAI_API_KEY")

    def run(key):
        return _run_analyze_transcript(transcript_data, key, progress_callback, provider)

    return try_with_rate_limit_fallback(provider, api_key, openai_key, run)
