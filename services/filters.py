"""
Rule-Based Quality Filters

Applied BEFORE rendering to reject low-quality clips deterministically.
No LLM calls — pure heuristics. Runs fast. Catches the embarrassing stuff.

Filters:
1. Mid-thought opening detection
2. Unresolved pronoun/context in first 5s
3. Incomplete/unresolved ending
4. Low emotional variance
5. Excessive dead air
6. Weak hook in first 3s
7. Semantic duplicate detection
"""

import re
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────

MID_THOUGHT_STARTERS = {
    "and", "but", "so", "because", "or", "also", "then", "plus",
    "however", "therefore", "meanwhile", "furthermore", "moreover",
    "anyway", "anyways", "anyhow", "though", "although", "unless",
    "except", "besides", "still", "yet", "nonetheless", "nevertheless",
    "otherwise", "instead", "similarly", "likewise", "accordingly",
    "consequently", "hence", "thus", "thereupon", "whereupon",
}

WEAK_HOOK_STARTERS = {
    "so", "um", "uh", "like", "you know", "i mean", "well", "okay",
    "ok", "yeah", "yes", "no", "right", "actually", "basically",
    "honestly", "literally", "i think", "i feel", "i believe",
    "in my opinion", "i guess", "i suppose", "maybe", "perhaps",
}

UNBOUND_PRONOUNS = {
    "he", "she", "they", "them", "it", "this", "that", "these",
    "those", "his", "her", "their", "its", "him",
}

RESOLUTION_INDICATORS = {
    ".", "!", "?",
    "that's why", "and that's", "so that's", "that is why",
    "in conclusion", "to sum up", "the point is", "here's the thing",
    "bottom line", "end of story", "that's the truth",
    "and that changed everything", "never looked back",
    "rest is history",
}

INCOMPLETE_ENDING_PATTERNS = [
    re.compile(r'\b(and|but|so|or|because|if|when|while|although|unless|until)\s*$', re.IGNORECASE),
    re.compile(r'\b(is|are|was|were|has|have|had|will|would|could|should|might|must|can|may)\s*$', re.IGNORECASE),
    re.compile(r'\b(the|a|an|to|in|on|at|by|for|with|from|of|about)\s*$', re.IGNORECASE),
    re.compile(r'\b(i|you|we|he|she|it|they)\s+(was|were|am|is|are|will|would)\s*$', re.IGNORECASE),
    re.compile(r'\.\.\.\s*$'),
    re.compile(r'—\s*$'),
]


# ── Filter 1: Mid-Thought Opening ───────────────────────────────

def check_mid_thought_opening(words: List[dict], clip_start: float) -> Tuple[bool, str]:
    """
    Check if a clip starts mid-thought based on the first spoken words.
    Returns (is_problem, reason).
    """
    if not words:
        return True, "No words in clip"

    # Get first 3 words after clip_start
    opening_words = [
        w for w in words
        if w["start"] >= clip_start
    ][:5]

    if not opening_words:
        return True, "No words at clip start"

    first_text = " ".join(w["word"] for w in opening_words[:3]).lower().strip()

    # Check if starts with mid-thought connector
    first_word = opening_words[0]["word"].lower().strip().strip('.,!?:;()"')
    if first_word in MID_THOUGHT_STARTERS:
        return True, f"Starts mid-thought: '{first_word}'"

    # Check for pronouns without antecedent in first 3 words
    pronoun_count = 0
    for w in opening_words[:5]:
        if w["word"].lower().strip() in UNBOUND_PRONOUNS:
            pronoun_count += 1
    if pronoun_count >= 2:
        return True, f"High unbound pronoun density ({pronoun_count}) in opening"

    # Check if first utterance is a dependent clause fragment
    fragment_patterns = [
        re.compile(r'^(and|but|so|because|if|when|while|since|although|unless|until)\s', re.IGNORECASE),
        re.compile(r'^(which|who|whom|whose|that)\s', re.IGNORECASE),
    ]
    for pattern in fragment_patterns:
        if pattern.match(first_text):
            return True, f"Dependent clause fragment opening: '{first_text[:40]}'"

    return False, ""


# ── Filter 2: Unresolved Context ────────────────────────────────

def check_unresolved_context(words: List[dict], clip_start: float) -> Tuple[bool, str]:
    """
    Check if the first 5 seconds contain references that need external context.
    """
    window_words = [
        w for w in words
        if clip_start <= w["start"] <= clip_start + 5.0
    ]
    if not window_words:
        return True, "No words in first 5 seconds"

    text = " ".join(w["word"] for w in window_words).lower()

    # Unresolved demonstratives without nearby referent
    demonstrative_patterns = [
        (r'\bthis (guy|man|woman|person|dude|thing|stuff|idea|concept|approach|method|strategy|way)\b', "unresolved 'this X'"),
        (r'\bthat (guy|man|woman|person|dude|thing|stuff|idea|concept|approach|method|strategy|way)\b', "unresolved 'that X'"),
        (r'\bthese (guys|people|things|guys|folks|ones)\b', "unresolved 'these X'"),
        (r'\bthose (guys|people|things|guys|folks|ones)\b', "unresolved 'those X'"),
        (r'\bhe (said|was|did|went|told|thought|knew|had)\b', "unresolved 'he' + action"),
        (r'\bshe (said|was|did|went|told|thought|knew|had)\b', "unresolved 'she' + action"),
        (r'\bthey (said|were|did|went|told|thought|knew|had)\b', "unresolved 'they' + action"),
    ]

    for pattern, label in demonstrative_patterns:
        if re.search(pattern, text):
            return True, label

    # The "naked pronoun" test: first spoken word is a pronoun
    first_word = window_words[0]["word"].lower().strip().strip('.,!?:;()"')
    if first_word in {"he", "she", "they", "it", "we"}:
        # Check if name/entity appears within next 3 seconds
        next_words = [w for w in window_words[1:10]
                      if window_words[0]["start"] <= w["start"] <= window_words[0]["start"] + 3.0]
        next_text = " ".join(w["word"] for w in next_words).lower()
        if not re.search(r'\b[A-Z][a-z]+\b', next_text):
            return True, f"Naked pronoun '{first_word}' without named entity in following 3s"

    return False, ""


# ── Filter 3: Incomplete/Unresolved Ending ──────────────────────

def check_ending_quality(words: List[dict], clip_end: float) -> Tuple[bool, str]:
    """
    Check if the clip ending is satisfying and complete.
    """
    if not words:
        return True, "No words"

    # Get last several words before clip_end
    ending_words = [
        w for w in words
        if w["start"] <= clip_end
    ][-8:]

    if not ending_words:
        return True, "No words at clip end"

    ending_text = " ".join(w["word"] for w in ending_words)

    # Check for incomplete sentence patterns
    for pattern in INCOMPLETE_ENDING_PATTERNS:
        if pattern.search(ending_text):
            return True, f"Incomplete ending: ends mid-clause ({pattern.pattern[:40]}...)"

    # Check if last word is a dangling connector
    last_word = ending_words[-1]["word"].lower().strip().strip('.,!?:;()"')
    if last_word in MID_THOUGHT_STARTERS:
        return True, f"Ends with connector: '{last_word}'"

    # Check for strong ending (resolution)
    has_resolution = False
    for indicator in RESOLUTION_INDICATORS:
        if indicator in ending_text.lower():
            has_resolution = True
            break

    if not has_resolution and len(ending_words) > 3:
        # Check if last utterance sounds like a trailing thought
        if not any(c in ending_words[-1]["word"] for c in ".!?"):
            return True, "No terminal punctuation at ending, possible incomplete thought"

    return False, ""


# ── Filter 4: Low Emotional Variance ────────────────────────────

def check_emotional_variance(sentiment_data: dict) -> Tuple[bool, str]:
    """
    Check if the clip has sufficient emotional range.
    Flat affect = boring clip.
    """
    segments = sentiment_data.get("segments", [])
    if len(segments) < 2:
        return True, "Insufficient segments for emotional analysis"

    sentiments = [s.get("sentiment", 0) for s in segments]
    arousals = [s.get("arousal", 0) for s in segments]

    sentiment_range = max(sentiments) - min(sentiments)
    arousal_max = max(arousals) if arousals else 0

    if sentiment_range < 0.02 and arousal_max < 0.05:
        return True, f"Flat emotional profile (range={sentiment_range:.4f}, max_arousal={arousal_max:.4f})"

    return False, ""


# ── Filter 5: Excessive Dead Air ────────────────────────────────

def check_dead_air(pause_data: dict, clip_duration: float) -> Tuple[bool, str]:
    """
    Reject clips with excessive dead air relative to duration.
    """
    dead_air_segments = pause_data.get("dead_air_segments", [])
    total_dead = sum(d.get("duration", 0) for d in dead_air_segments)

    if clip_duration <= 0:
        return True, "Invalid clip duration"

    dead_ratio = total_dead / clip_duration

    if dead_ratio > 0.35:
        return True, f"Excessive dead air: {total_dead:.1f}s ({dead_ratio:.0%} of clip)"

    if len(dead_air_segments) >= 3:
        return True, f"Too many dead air gaps: {len(dead_air_segments)} gaps > 2s"

    return False, ""


# ── Filter 6: Weak Hook ─────────────────────────────────────────

def check_hook_strength(words: List[dict], clip_start: float, signals: dict) -> Tuple[bool, str]:
    """
    Check if the first 3 seconds have a compelling hook.
    """
    hook_words = [
        w for w in words
        if clip_start <= w["start"] <= clip_start + 3.0
    ]
    if not hook_words:
        return True, "No words in hook window (first 3s)"

    first_3_text = " ".join(w["word"] for w in hook_words).lower().strip()

    # Weak hook starters
    first_word = hook_words[0]["word"].lower().strip().strip('.,!?:;()"')
    if first_word in WEAK_HOOK_STARTERS:
        return True, f"Weak hook starter: '{first_word}'"

    # Too few words in hook = slow opening
    if len(hook_words) < 4:
        return True, f"Slow opening: only {len(hook_words)} words in first 3s"

    # Check for question hooks (good)
    has_question = any("?" in w["word"] for w in hook_words)

    # Check for statement hooks with no hook markers
    hook_markers = [
        "never", "always", "secret", "hidden", "nobody", "everyone",
        "most", "worst", "best", "huge", "massive", "shocking",
        "imagine", "what if", "the truth", "i discovered",
    ]
    has_hook_marker = any(marker in first_3_text for marker in hook_markers)

    if not has_question and not has_hook_marker:
        # Check pacing: very slow hook = bad
        hook_duration = hook_words[-1]["end"] - hook_words[0]["start"]
        if hook_duration > 0:
            hook_wpm = (len(hook_words) / hook_duration) * 60
            if hook_wpm < 80:
                return True, f"Weak hook pacing: only {hook_wpm:.0f} WPM"

    return False, ""


# ── Filter 7: Semantic Duplicate ─────────────────────────────────

def compute_text_overlap(text1: str, text2: str) -> float:
    """Jaccard similarity of word sets."""
    if not text1 or not text2:
        return 0.0
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)


def check_semantic_duplicate(clip: dict, existing_clips: List[dict],
                              transcript_words: List[dict]) -> Tuple[bool, str]:
    """
    Check if this clip is a semantic duplicate of an already-accepted clip.
    Uses text overlap > 60% as threshold.
    """
    if not existing_clips:
        return False, ""

    clip_words = [
        w["word"] for w in transcript_words
        if clip["start_time"] <= w.get("start", 0) <= clip["end_time"]
    ]
    clip_text = " ".join(clip_words)

    temporal_overlap_threshold = 0.85

    for existing in existing_clips:
        existing_words = [
            w["word"] for w in transcript_words
            if existing["start_time"] <= w.get("start", 0) <= existing["end_time"]
        ]
        existing_text = " ".join(existing_words)

        # Temporal overlap
        overlap_start = max(clip["start_time"], existing["start_time"])
        overlap_end = min(clip["end_time"], existing["end_time"])
        clip_dur = clip["end_time"] - clip["start_time"]
        if clip_dur > 0:
            temporal_overlap = (overlap_end - overlap_start) / clip_dur
            if temporal_overlap > temporal_overlap_threshold:
                return True, f"Temporal duplicate: {temporal_overlap:.0%} overlap with existing clip"

        # Text similarity
        similarity = compute_text_overlap(clip_text, existing_text)
        if similarity > 0.6:
            return True, f"Semantic duplicate: {similarity:.0%} word overlap"

    return False, ""


# ── Master Filter Runner ────────────────────────────────────────

def run_all_filters(clip: dict, words: List[dict], segments: List[dict],
                     signals: dict, accepted_clips: List[dict] = None) -> Dict[str, any]:
    """
    Run all quality filters on a candidate clip. Returns filter results.
    clip must have: start_time, end_time
    """
    if accepted_clips is None:
        accepted_clips = []

    start = clip["start_time"]
    end = clip["end_time"]
    duration = end - start

    results = {
        "passed": True,
        "rejections": [],
        "warnings": [],
        "scores": {},
    }

    # Filter 1: Mid-thought opening
    is_mid, reason = check_mid_thought_opening(words, start)
    if is_mid:
        results["passed"] = False
        results["rejections"].append({"filter": "mid_thought_opening", "reason": reason})
        return results  # Hard stop — can't fix mid-thought
    results["scores"]["mid_thought_pass"] = True

    # Filter 2: Unresolved context
    is_unresolved, reason = check_unresolved_context(words, start)
    if is_unresolved:
        results["passed"] = False
        results["rejections"].append({"filter": "unresolved_context", "reason": reason})
        return results  # Hard stop
    results["scores"]["context_resolved"] = True

    # Filter 3: Ending quality
    is_bad_end, reason = check_ending_quality(words, end)
    if is_bad_end:
        results["passed"] = False
        results["rejections"].append({"filter": "incomplete_ending", "reason": reason})
    else:
        results["scores"]["ending_quality_pass"] = True

    # Filter 4: Emotional variance
    sentiment_data = signals.get("sentiment", {}) if signals else {}
    is_flat, reason = check_emotional_variance(sentiment_data)
    if is_flat:
        results["warnings"].append({"filter": "low_emotional_variance", "reason": reason})
    else:
        results["scores"]["emotional_variance_pass"] = True

    # Filter 5: Dead air
    pause_data = signals.get("pauses", {}) if signals else {}
    is_dead, reason = check_dead_air(pause_data, duration)
    if is_dead:
        results["passed"] = False
        results["rejections"].append({"filter": "excessive_dead_air", "reason": reason})
    else:
        results["scores"]["dead_air_pass"] = True

    # Filter 6: Hook strength
    is_weak_hook, reason = check_hook_strength(words, start, signals)
    if is_weak_hook:
        results["warnings"].append({"filter": "weak_hook", "reason": reason})
    else:
        results["scores"]["hook_strength_pass"] = True

    # Filter 7: Semantic duplicate
    is_dupe, reason = check_semantic_duplicate(clip, accepted_clips, words)
    if is_dupe:
        results["passed"] = False
        results["rejections"].append({"filter": "semantic_duplicate", "reason": reason})
    else:
        results["scores"]["semantic_unique_pass"] = True

    return results


def generate_filter_report(filter_results: dict) -> str:
    """Generate a human-readable filter report for QA dashboard."""
    lines = []

    if filter_results["passed"]:
        lines.append("✅ ALL FILTERS PASSED")
    else:
        lines.append("❌ FILTERS FAILED")
        for r in filter_results.get("rejections", []):
            lines.append(f"  • {r['filter']}: {r['reason']}")

    if filter_results.get("warnings"):
        lines.append("⚠️  WARNINGS")
        for w in filter_results["warnings"]:
            lines.append(f"  • {w['filter']}: {w['reason']}")

    return "\n".join(lines)
