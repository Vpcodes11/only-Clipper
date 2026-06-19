"""
Pre-LLM Signal Computation Engine

Computes objective audio/textual signals from transcript data BEFORE the LLM sees it.
These signals feed into clip scoring, filtering, and prompt enrichment.

Signals computed:
- pacing acceleration / deceleration
- pause density & anomaly detection
- speech intensity variance
- lexical novelty (TF-IDF within transcript)
- sentiment shift magnitude
- emotional spike detection
- segment arousal scoring
"""

import math
import logging
from collections import Counter
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


# ── Lexical Novelty (lightweight TF-IDF within transcript) ─────

def _tokenize(text: str) -> List[str]:
    return text.lower().strip().split()


def _compute_tf_idf_within_transcript(segments: List[dict]) -> Dict[str, float]:
    """
    Compute TF-IDF scores for each word across the transcript.
    Words unique to one segment get high scores; common words get low scores.
    No external library needed — pure Python.
    """
    total_docs = len(segments)
    if total_docs <= 1:
        return {}

    doc_texts = [seg.get("text", "") for seg in segments]
    doc_tokens = [_tokenize(t) for t in doc_texts]

    # Document frequency
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))

    # IDF
    idf = {}
    for word, count in df.items():
        if count == 0:
            continue
        idf[word] = math.log((total_docs + 1) / (count + 1)) + 1.0

    # Per-segment TF-IDF sum (returned as average per segment)
    segment_scores = {}
    for i, tokens in enumerate(doc_tokens):
        if not tokens:
            segment_scores[i] = 0.0
            continue
        tf = Counter(tokens)
        total = sum(
            (tf[w] / len(tokens)) * idf.get(w, 0.0)
            for w in set(tokens)
        )
        segment_scores[i] = total

    return segment_scores


# ── Pacing & Intensity ──────────────────────────────────────────

def compute_pacing_signals(words: List[dict], segments: List[dict]) -> dict:
    """
    Compute pacing signals per segment: WPM, acceleration, variance.
    Returns segment-level pacing data and global statistics.
    """
    if not words or not segments:
        return {"segment_pacing": [], "global_wpm": 0, "pacing_variance": 0}

    segment_pacing = []
    wpms = []

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        dur = seg_end - seg_start
        if dur <= 0:
            segment_pacing.append({"wpm": 0, "accel": 0, "dur": dur})
            continue

        seg_words = [w for w in words if seg_start <= w["start"] < seg_end]
        wpm = (len(seg_words) / dur) * 60
        wpms.append(wpm)

        segment_pacing.append({
            "wpm": round(wpm, 1),
            "dur": round(dur, 2),
            "word_count": len(seg_words),
        })

    # Compute acceleration (delta between consecutive segments)
    for i in range(1, len(segment_pacing)):
        prev_wpm = segment_pacing[i - 1]["wpm"]
        curr_wpm = segment_pacing[i]["wpm"]
        prev_dur = segment_pacing[i - 1]["dur"]
        if prev_dur > 0:
            segment_pacing[i]["accel"] = round((curr_wpm - prev_wpm) / prev_dur, 2)
        else:
            segment_pacing[i]["accel"] = 0.0
    if segment_pacing:
        segment_pacing[0]["accel"] = 0.0

    # Global stats
    global_wpm = sum(wpms) / len(wpms) if wpms else 0
    variance = sum((w - global_wpm) ** 2 for w in wpms) / len(wpms) if wpms else 0

    return {
        "segment_pacing": segment_pacing,
        "global_wpm": round(global_wpm, 1),
        "pacing_variance": round(variance, 1),
        "max_wpm": round(max(wpms), 1) if wpms else 0,
        "min_wpm": round(min(wpms), 1) if wpms else 0,
    }


def compute_pause_signals(words: List[dict]) -> dict:
    """
    Detect pauses between words and compute anomaly scores.
    A pause > 0.8s is notable. Pauses > 2.0s are anomalous/dead air.
    """
    if not words or len(words) < 2:
        return {"pauses": [], "pause_count": 0, "dead_air_segments": [], "mean_pause": 0}

    pauses = []
    dead_air = []

    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap >= 0.8:
            pauses.append({
                "start": round(words[i]["end"], 2),
                "end": round(words[i + 1]["start"], 2),
                "duration": round(gap, 2),
                "before_word": words[i]["word"],
                "after_word": words[i + 1]["word"],
            })
            if gap >= 2.0:
                dead_air.append(pauses[-1])

    mean_pause = sum(p["duration"] for p in pauses) / len(pauses) if pauses else 0
    pause_density = len(pauses) / (words[-1]["end"] - words[0]["start"]) * 60 if len(words) > 1 else 0

    return {
        "pauses": pauses,
        "pause_count": len(pauses),
        "dead_air_segments": dead_air,
        "mean_pause": round(mean_pause, 2),
        "pause_density_per_minute": round(pause_density, 2),
    }


def compute_intensity_signals(words: List[dict], segments: List[dict]) -> dict:
    """
    Speech intensity: word density variance, burst detection.
    Rapid dense bursts = high intensity. Sparse speech = low intensity.
    """
    if not words or not segments:
        return {"segments": [], "global_intensity_variance": 0}

    seg_intensities = []

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        dur = seg_end - seg_start
        if dur <= 0:
            seg_intensities.append({"intensity": 0, "is_burst": False})
            continue

        seg_words = [w for w in words if seg_start <= w["start"] < seg_end]
        text = seg.get("text", "")
        chars_per_sec = len(text) / dur
        words_per_sec = len(seg_words) / dur

        # Burst detection: > 3 words/sec is a burst
        is_burst = words_per_sec > 3.0

        seg_intensities.append({
            "intensity": round(words_per_sec, 2),
            "char_rate": round(chars_per_sec, 1),
            "word_count": len(seg_words),
            "is_burst": is_burst,
        })

    intensity_values = [s["intensity"] for s in seg_intensities]
    mean_intensity = sum(intensity_values) / len(intensity_values) if intensity_values else 0
    variance = sum((v - mean_intensity) ** 2 for v in intensity_values) / len(intensity_values) if intensity_values else 0

    return {
        "segments": seg_intensities,
        "global_intensity_variance": round(variance, 4),
        "mean_intensity": round(mean_intensity, 2),
        "burst_count": sum(1 for s in seg_intensities if s.get("is_burst")),
    }


# ── Sentiment & Emotion ─────────────────────────────────────────

def compute_sentiment_signals(segments: List[dict]) -> dict:
    """
    Lightweight sentiment/emotional analysis using keyword heuristics.
    No external NLP dependency — uses curated word lists.
    Returns per-segment sentiment scores and emotional arc data.
    """
    POSITIVE = {
        "love", "great", "amazing", "best", "beautiful", "incredible", "wonderful",
        "fantastic", "excellent", "happy", "joy", "success", "win", "powerful",
        "freedom", "yes", "absolutely", "perfect", "brilliant", "awesome", "blessed",
        "grateful", "opportunity", "breakthrough", "growth", "abundance",
    }
    NEGATIVE = {
        "hate", "terrible", "worst", "awful", "horrible", "disgusting", "failure",
        "lose", "death", "pain", "suffering", "fear", "angry", "sad", "depressed",
        "broke", "destroyed", "never", "impossible", "struggle", "crisis", "danger",
        "warning", "disaster", "tragedy", "nightmare",
    }
    HIGH_AROUSAL = {
        "insane", "crazy", "shocking", "exposed", "dangerous", "never", "always",
        "must", "now", "stop", "huge", "massive", "explosive", "breakthrough",
        "revolution", "game-changer", "unstoppable", "incredible", "unbelievable",
        "literally", "absolutely", "goosebumps", "chills", "mind-blowing",
    }
    CURIOSITY = {
        "secret", "hidden", "revealed", "discovered", "nobody", "behind", "truth",
        "what if", "imagine", "surprising", "unexpected", "mystery", "unknown",
        "trick", "hack", "method", "formula", "blueprint", "system", "loophole",
    }

    if not segments:
        return {"segments": [], "global_sentiment_trend": [], "emotional_peaks": []}

    seg_sentiments = []
    sentiment_values = []

    for seg in segments:
        text = seg.get("text", "").lower()
        words_set = set(text.split())

        pos = len(words_set & POSITIVE)
        neg = len(words_set & NEGATIVE)
        arousal = len(words_set & HIGH_AROUSAL)
        curiosity = len(words_set & CURIOSITY)

        total = len(words_set) or 1
        sentiment_score = (pos - neg) / max(total, 1)
        arousal_score = arousal / max(total, 1)
        curiosity_score = curiosity / max(total, 1)

        sentiment_values.append(sentiment_score)

        seg_sentiments.append({
            "start": round(seg.get("start", 0), 1),
            "sentiment": round(sentiment_score, 4),
            "arousal": round(arousal_score, 4),
            "curiosity": round(curiosity_score, 4),
            "pos_words": pos,
            "neg_words": neg,
        })

    # Emotional peaks: segments where sentiment swing is highest
    sentiment_deltas = []
    for i in range(1, len(sentiment_values)):
        delta = sentiment_values[i] - sentiment_values[i - 1]
        sentiment_deltas.append({
            "index": i,
            "delta": round(delta, 4),
            "start": seg_sentiments[i]["start"],
            "direction": "positive" if delta > 0 else "negative",
        })

    sentiment_deltas.sort(key=lambda x: abs(x["delta"]), reverse=True)
    emotional_peaks = sentiment_deltas[:5]

    return {
        "segments": seg_sentiments,
        "global_sentiment_trend": sentiment_values,
        "emotional_peaks": emotional_peaks,
        "mean_sentiment": round(sum(sentiment_values) / len(sentiment_values), 4) if sentiment_values else 0,
    }


# ── Viral Quality Signals ─────────────────────────────────────────

def compute_viral_signals(segments: List[dict], words: List[dict]) -> dict:
    """
    Detect viral-quality linguistic patterns from transcript text.
    Identifies markers that human editors look for:
    - Contrarian statements / hot takes
    - Personal stories / confessions
    - Strong opinions / emotional declarations
    - Punchy / quotable one-liners
    - Curiosity-triggering setups
    - Transformation / lesson language
    """
    CONTRARIAN_MARKERS = {
        "but here's", "actually", "the opposite", "contrary", "most people think",
        "everyone thinks", "nobody talks about", "what they don't tell you",
        "the truth is", "here's the thing", "here's what", "unpopular opinion",
        "controversial", "hot take", "hear me out", "i used to think",
        "i changed my mind", "i was wrong", "surprisingly", "believe it or not",
        "you'd think", "it turns out", "turns out", "the reality is",
        "the difference between", "what most people don't realize",
    }
    PERSONAL_STORY_MARKERS = {
        "i remember", "i was", "i had", "i did", "i went", "i said",
        "this one time", "back when i", "when i was", "my", "me",
        "i made", "i learned", "i discovered", "i realized", "i noticed",
        "i started", "i tried", "i failed", "i quit", "i built",
        "we decided", "we started", "we built", "we failed", "we almost",
        "let me tell you", "i'll never forget", "the moment i",
    }
    STRONG_OPINION_MARKERS = {
        "the best", "the worst", "the greatest", "the biggest",
        "i hate", "i love", "i can't stand", "i refuse", "i believe",
        "absolutely", "completely", "totally", "literally",
        "never", "always", "everyone", "nobody", "no one",
        "impossible", "guaranteed", "destroyed", "ruined", "changed",
        "game changer", "breakthrough", "revolution", "massive", "huge",
        "this is why", "that's why", "because", "the reason",
    }
    CURIOSITY_SETUP_MARKERS = {
        "imagine", "what if", "what happens when", "how would you",
        "here's the problem", "the problem is", "the question is",
        "you won't believe", "wait until", "the secret", "the hidden",
        "what nobody", "what most people", "have you ever",
        "ever wonder", "think about", "consider this",
        "this is going to", "prepare for",
    }
    TRANSFORMATION_MARKERS = {
        "changed everything", "turned my life", "completely different",
        "from that moment", "never looked back", "changed the way",
        "completely changed", "transformed", "breakthrough", "turning point",
        "i learned", "i realized", "i discovered", "it taught me",
        "the lesson", "what i learned", "here's what i know now",
        "if i could go back", "looking back", "in hindsight",
        "the biggest lesson", "the most important thing",
    }
    PUNCHY_PATTERNS = [
        re.compile(r'^[A-Z][a-z]+ is [A-Za-z]+\.$'),  # "X is Y." — definitive one-liner
        re.compile(r'^That\'s why'),  # "That's why X..."
        re.compile(r'\. (That|This|Here)'),  # Short punchy sentence starting new
    ]

    if not segments:
        return {"segment_viral_scores": [], "viral_peaks": [], "global_viral_heat": 0}

    segment_viral = []
    viral_peaks = []

    for i, seg in enumerate(segments):
        text = seg.get("text", "").lower()
        start = seg.get("start", 0)

        contrarian_count = sum(1 for m in CONTRARIAN_MARKERS if m in text)
        story_count = sum(1 for m in PERSONAL_STORY_MARKERS if m in text)
        opinion_count = sum(1 for m in STRONG_OPINION_MARKERS if m in text)
        curiosity_count = sum(1 for m in CURIOSITY_SETUP_MARKERS if m in text)
        transform_count = sum(1 for m in TRANSFORMATION_MARKERS if m in text)
        punchy_count = 0
        for pat in PUNCHY_PATTERNS:
            if pat.search(text):
                punchy_count += 1

        # Composite viral heat for this segment
        viral_heat = (
            contrarian_count * 3.0 +      # Contrarian = highest signal
            story_count * 2.0 +            # Personal stories
            opinion_count * 2.0 +          # Strong opinions
            curiosity_count * 2.5 +        # Curiosity setups
            transform_count * 2.0 +         # Transformation language
            punchy_count * 3.0             # Punchy one-liners
        )

        # Cap and normalize per segment
        viral_heat = min(viral_heat, 10.0)

        segment_viral.append({
            "start": round(start, 1),
            "viral_heat": round(viral_heat, 2),
            "contrarian": contrarian_count,
            "personal_story": story_count,
            "strong_opinion": opinion_count,
            "curiosity_setup": curiosity_count,
            "transformation": transform_count,
            "punchy": punchy_count,
            "has_personal_pronoun": bool(re.search(r'\b(i|we|my|our|me)\b', text)),
            "has_contrarian": contrarian_count > 0,
            "has_opinion": opinion_count > 0,
        })

        if viral_heat >= 5.0:
            viral_peaks.append({
                "start": start,
                "heat": round(viral_heat, 2),
                "type": "contrarian" if contrarian_count > 0 else "story" if story_count > 0 else "opinion" if opinion_count > 0 else "curiosity",
            })

    global_heat = sum(s["viral_heat"] for s in segment_viral) / max(len(segment_viral), 1)

    return {
        "segment_viral_scores": segment_viral,
        "viral_peaks": viral_peaks,
        "global_viral_heat": round(global_heat, 2),
        "peak_count": len(viral_peaks),
        "has_contrarian_content": any(s["has_contrarian"] for s in segment_viral),
        "has_personal_stories": any(s["personal_story"] > 0 for s in segment_viral),
        "has_strong_opinions": any(s["has_opinion"] for s in segment_viral),
    }


# ── Combined Signal Extraction ──────────────────────────────────

def extract_all_signals(words: List[dict], segments: List[dict]) -> dict:
    """
    Master function: computes all pre-LLM signals from transcript data.
    Returns a structured dictionary ready for prompt enrichment.
    """
    pacing = compute_pacing_signals(words, segments)
    pauses = compute_pause_signals(words)
    intensity = compute_intensity_signals(words, segments)
    sentiment = compute_sentiment_signals(segments)
    lexical_novelty = _compute_tf_idf_within_transcript(segments)
    viral = compute_viral_signals(segments, words)

    return {
        "pacing": pacing,
        "pauses": pauses,
        "intensity": intensity,
        "sentiment": sentiment,
        "lexical_novelty": lexical_novelty,
        "viral": viral,
    }


def compute_segment_signal_summary(segments: List[dict], words: List[dict],
                                    start_time: float, end_time: float) -> dict:
    """
    Compute a signal summary for a specific time window (potential clip).
    Used for pre-LLM scoring of candidate clip boundaries.
    """
    window_segments = [
        s for s in segments
        if s.get("start", 0) >= start_time - 1.0 and s.get("end", 0) <= end_time + 1.0
    ]
    window_words = [
        w for w in words
        if start_time <= w.get("start", 0) <= end_time
    ]

    if not window_segments:
        return {}

    # Pacing in window
    pacing = compute_pacing_signals(window_words, window_segments)
    pauses = compute_pause_signals(window_words)
    intensity = compute_intensity_signals(window_words, window_segments)
    sentiment = compute_sentiment_signals(window_segments)

    # Composite pre-LLM score
    sentiment_swing = max(
        abs(s["sentiment"]) for s in sentiment.get("segments", [{}])
    ) if sentiment.get("segments") else 0

    burst_ratio = (
        intensity.get("burst_count", 0) / max(len(window_segments), 1)
    )
    dead_air_count = len(pauses.get("dead_air_segments", []))
    pacing_variance = pacing.get("pacing_variance", 0)
    mean_arousal = sum(
        s.get("arousal", 0) for s in sentiment.get("segments", [{}])
    ) / max(len(sentiment.get("segments", [{}])), 1)

    pre_llm_score = (
        min(sentiment_swing * 2.5, 2.5) +
        min(burst_ratio * 2.0, 2.0) +
        min(pacing_variance / 50, 1.5) +
        max(0, 2.0 - dead_air_count * 1.0) +
        min(mean_arousal * 15, 2.0)
    )

    return {
        "pre_llm_score": round(pre_llm_score, 2),
        "sentiment_swing": round(sentiment_swing, 4),
        "burst_ratio": round(burst_ratio, 2),
        "dead_air_sections": dead_air_count,
        "pacing_variance": pacing_variance,
        "mean_arousal": round(mean_arousal, 4),
        "pacing": pacing,
        "pauses": pauses,
        "intensity": intensity,
        "sentiment": sentiment,
    }


def format_signals_for_prompt(signals: dict, start_time: float, end_time: float) -> str:
    """
    Formats pre-computed signals as structured metadata text for LLM prompts.
    Now includes viral quality signals (contrarian, story, opinion markers).
    """
    pacing = signals.get("pacing", {})
    sentiment = signals.get("sentiment", {})
    pauses = signals.get("pauses", {})
    intensity = signals.get("intensity", {})
    viral = signals.get("viral", {})

    emotional_peaks = sentiment.get("emotional_peaks", [])
    peaks_in_window = [
        p for p in emotional_peaks
        if start_time - 5 <= p.get("start", 0) <= end_time + 5
    ]

    dead_air = [d for d in pauses.get("dead_air_segments", [])
                if start_time <= d.get("start", 0) <= end_time]

    lines = []
    lines.append(f"[Signal Metadata for {start_time:.1f}s - {end_time:.1f}s]")

    if pacing:
        lines.append(f"Speaking pace: avg {pacing.get('global_wpm', '?')} WPM, "
                     f"variance {pacing.get('pacing_variance', '?')}")

    if peaks_in_window:
        peak_descs = [f"{p['direction']} shift at {p['start']}s (delta {p['delta']})"
                       for p in peaks_in_window[:3]]
        lines.append(f"Emotional shifts: {'; '.join(peak_descs)}")

    if dead_air:
        lines.append(f"Dead air sections: {len(dead_air)} gaps > 2s")

    if intensity:
        lines.append(f"Speech bursts: {intensity.get('burst_count', 0)} high-intensity segments")

    # Viral quality signals
    viral_peaks = [p for p in viral.get("viral_peaks", [])
                   if start_time <= p.get("start", 0) <= end_time]
    viral_segs = [s for s in viral.get("segment_viral_scores", [])
                  if start_time <= s.get("start", 0) <= end_time]
    if viral_segs:
        avg_heat = sum(s["viral_heat"] for s in viral_segs) / max(len(viral_segs), 1)
        types = []
        if any(s["has_contrarian"] for s in viral_segs):
            types.append("contrarian")
        if any(s["has_opinion"] for s in viral_segs):
            types.append("strong_opinion")
        if any(s["personal_story"] > 0 for s in viral_segs):
            types.append("personal_story")
        lines.append(f"Viral heat: {avg_heat:.1f}/10 — markers: {', '.join(types) if types else 'none detected'}")

    if sentiment:
        p_var = pacing.get("pacing_variance", 0)
        b_count = intensity.get("burst_count", 0)
        n_seg = max(len(sentiment.get("segments", [])), 1)
        mean_arousal = sum(s.get("arousal", 0) for s in sentiment.get("segments", [])) / n_seg
        dead_count = len([d for d in pauses.get("dead_air_segments", [])
                          if start_time <= d.get("start", 0) <= end_time])
        pre_llm = (
            min(p_var / 50, 2.5) +
            min(b_count * 1.5, 3.0) +
            min(mean_arousal * 20, 2.5) +
            max(0, 2.0 - dead_count * 0.5)
        )
        lines.append(f"Composite signal score: {pre_llm:.1f}/10 (pacing_var={p_var:.0f}, bursts={b_count}, "
                     f"mean_arousal={mean_arousal:.3f}, dead_air={dead_count})")

    return "\n".join(lines)
