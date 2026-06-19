"""Video clipping and caption burning with FFmpeg"""
import subprocess
import os
import json
import functools
import logging
import hashlib
from pathlib import Path
from services.config import FFMPEG_TIMEOUT_SECONDS, FFPROBE_TIMEOUT_SECONDS, THUMBNAIL_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# Video output presets
PRESETS = {
    "tiktok": {"width": 1080, "height": 1920, "label": "TikTok / Reels (9:16)"},
    "youtube_shorts": {"width": 1080, "height": 1920, "label": "YouTube Shorts (9:16)"},
    "square": {"width": 1080, "height": 1080, "label": "Square (1:1)"},
    "landscape": {"width": 1920, "height": 1080, "label": "Landscape (16:9)"},
}

# Caption styles copied exactly from the audited codebase
CAPTION_STYLES = {
    "tiktok": {
        "font": "Montserrat ExtraBold",
        "fontsize": 85,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FFFF",  # Yellow
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "bold": True,
        "outline": 6,
        "shadow": 4,
        "alignment": 2,
        "margin_v": 120,
    },
    "minimal": {
        "font": "Inter",
        "fontsize": 72,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FF00",  # Green
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_v": 120,
    },
    "viral": {
        "font": "Montserrat Black",
        "fontsize": 110,
        "primary_color": "&H0000D4FF",  # Gold
        "highlight_color": "&H00FFFFFF",  # White
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 10,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 120,
    },
    "bold_impact": {
        "font": "Montserrat Black",
        "fontsize": 100,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H000022FF",  # Red
        "outline_color": "&H00000000",
        "back_color": "&H40000000",
        "bold": True,
        "outline": 10,
        "shadow": 8,
        "alignment": 2,
        "margin_v": 120,
    },
    "neon_pulse": {
        "font": "Outfit",
        "fontsize": 85,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H00FF00FF",  # Magenta
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 6,
        "shadow": 12,
        "alignment": 2,
        "margin_v": 120,
    },
    "karaoke": {
        "font": "Komika Axis",
        "fontsize": 90,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FFFF",  # Yellow
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 10,
        "shadow": 4,
        "alignment": 2,
        "margin_v": 120,
    },
    "high_intensity": {
        "font": "The Bold Font",
        "fontsize": 110,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FFFF",  # Yellow
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 12,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 120,
    },
    "minimal_modern": {
        "font": "Inter",
        "fontsize": 75,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H00FF00FF",  # Magenta
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 0,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 576,
    },
    "premium_aesthetic": {
        "font": "Montserrat Black",
        "fontsize": 110,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H0000FF00",  # Neon Green
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 12,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 120,
    },
    "typography_motion": {
        "font": "Montserrat Black",
        "secondary_font": "Segoe Script",
        "fontsize": 85,
        "primary_color": "&H0000D4FF",  # Gold
        "highlight_color": "&H00FFFFFF",  # White
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 10,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 80,
    },
    "stealth_pro": {
        "font": "Outfit",
        "fontsize": 95,
        "primary_color": "&H00FFFFFF",
        "highlight_color": "&H00F65C8B",  # Purple Accent
        "outline_color": "&H00000000",
        "back_color": "&H40000000",
        "bold": True,
        "outline": 8,
        "shadow": 12,
        "alignment": 2,
        "margin_v": 120,
    },
    "hormozi": {
        "font": "Montserrat Black",
        "fontsize": 105,
        "primary_color": "&H0000FFFF",  # Yellow inactive
        "highlight_color": "&H00FFFFFF",  # White active
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 8,
        "shadow": 6,
        "alignment": 2,
        "margin_v": 120,
    },
    "ali_abdaal": {
        "font": "Inter",
        "fontsize": 72,
        "primary_color": "&H00FFFFFF",  # White active
        "highlight_color": "&H00CCCCCC",  # Grey inactive
        "outline_color": "&H00000000",
        "back_color": "&H99000000",  # Semi-transparent box
        "bold": True,
        "outline": 0,
        "shadow": 0,
        "alignment": 5,  # Center
        "margin_v": 200,
    },
    "beast_mode": {
        "font": "Montserrat Black",
        "fontsize": 130,
        "primary_color": "&H000000FF",  # Red active
        "highlight_color": "&H00FFFFFF",  # White inactive
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "bold": True,
        "outline": 14,
        "shadow": 0,
        "alignment": 2,
        "margin_v": 80,
    },
}

POWER_WORDS = [
    "amazing", "secret", "never", "always", "money", "growth", "viral", "hacks", "life", "change", "fast", "easy",
    "simple", "power", "win", "lose", "stop", "start", "now", "today", "tomorrow", "don't", "can't", "must",
    "truth", "lies", "billion", "million", "rich", "poor", "success", "failure", "everything", "nothing",
    "insane", "crazy", "huge", "shocking", "exposed", "dangerous", "illegal", "hidden", "private", "dark",
    "light", "heaven", "hell", "god", "devil", "love", "hate", "fear", "brave", "strong", "weak",
    "wealth", "freedom", "prison", "breakout", "system", "matrix", "wake", "sleep", "dream", "real",
    "unlocked", "revealed", "leaked", "danger", "warning", "billionaire", "passive", "income", "quit",
    "boss", "fired", "empire", "legend", "warrior", "elite", "stealth", "intelligence", "neural",
]

EMOJIS = ["🚀", "🔥", "💎", "💰", "😱", "✅", "🛑", "👀", "🤯", "📈", "🎯", "🤫", "🦁", "👑"]

DEFAULT_CAPTION_STYLE = "typography_motion"

SAFE_FONT_FALLBACKS = {
    "Montserrat ExtraBold": ["Montserrat", "Arial Black", "Impact", "Arial"],
    "Montserrat Black": ["Montserrat", "Arial Black", "Impact", "Arial"],
    "Outfit": ["Arial", "Verdana", "Tahoma", "Sans"],
    "Komika Axis": ["Impact", "Arial Black", "Arial"],
    "The Bold Font": ["Impact", "Arial Black", "Arial"],
    "Segoe Script": ["Segoe UI", "Arial", "Verdana"],
    "Inter": ["Arial", "Verdana", "Tahoma"],
}
COMMON_FALLBACK_FONTS = ["Arial", "Verdana", "Tahoma", "Segoe UI", "Impact", "Sans"]


def escape_ass_text(text: str) -> str:
    """Escapes special ASS subtitle markers to prevent injection errors"""
    if not text:
        return text
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text


@functools.lru_cache(maxsize=64)
def _system_font_names():
    """Builds a cached set of lowercased available font family names on the OS"""
    names = set()
    import platform
    if platform.system() == "Windows":
        fonts_dir = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        if fonts_dir.is_dir():
            for path in fonts_dir.iterdir():
                if path.is_file():
                    names.add(path.stem.lower())
    else:
        for fonts_dir in [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts"]:
            if fonts_dir.is_dir():
                for path in fonts_dir.rglob("*"):
                    if path.suffix.lower() in (".ttf", ".otf", ".ttc") and path.is_file():
                        names.add(path.stem.lower())
    return names


def is_font_available(font_name: str) -> bool:
    """Check if the given font name is installed on the host system"""
    if not font_name:
        return False
    normalized = font_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    for f in _system_font_names():
        candidate = f.lower().replace(" ", "").replace("-", "").replace("_", "")
        if normalized in candidate or candidate in normalized:
            return True
    return False


def resolve_ass_font(font_name: str) -> str:
    """Resolves font name, falling back to clean cross-platform fallbacks if missing"""
    if not font_name:
        return "Arial"
    if is_font_available(font_name):
        return font_name
    for fallback in SAFE_FONT_FALLBACKS.get(font_name, []):
        if is_font_available(fallback):
            return fallback
    for fallback in COMMON_FALLBACK_FONTS:
        if is_font_available(fallback):
            return fallback
    return "Arial"


@functools.lru_cache(maxsize=32)
def get_video_info(video_path):
    """Retrieves video width, height, and duration using ffprobe"""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-show_entries', 'stream=width,height,codec_type',
        '-show_entries', 'format=duration',
        '-of', 'json', video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=FFPROBE_TIMEOUT_SECONDS)
    data = json.loads(result.stdout)

    width, height = 1920, 1080
    for stream in data.get('streams', []):
        if stream.get('codec_type') == 'video':
            width = int(stream.get('width', 1920))
            height = int(stream.get('height', 1080))
            break

    duration = float(data.get('format', {}).get('duration', 0.0))
    return width, height, duration


def generate_thumbnail(video_path, start_time, output_path):
    """Generates a JPEG thumbnail image from the video segment"""
    cmd = [
        'ffmpeg', '-ss', str(start_time + 1.0),
        '-i', video_path,
        '-vframes', '1',
        '-vf', 'scale=360:-2',
        '-q:v', '4',
        '-y', output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=THUMBNAIL_TIMEOUT_SECONDS)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("Thumbnail extraction timed out.")
        return False


def format_ass_time(seconds):
    """Converts seconds float to ASS time format: H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    if cs == 100:
        cs = 0
        s += 1
        if s == 60:
            s = 0
            m += 1
            if m == 60:
                m = 0
                h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_subtitles(words, clip_start, clip_end, output_path, caption_style=None, preset="tiktok", hook_headline=None):
    """Generates an ASS subtitle file featuring word-level karaoke coloring & top hook headline"""
    if not caption_style or caption_style not in CAPTION_STYLES:
        caption_style = DEFAULT_CAPTION_STYLE

    style = CAPTION_STYLES[caption_style]

    clip_words = [
        w for w in words
        if w['start'] >= clip_start - 0.5 and w['end'] <= clip_end + 0.5
    ]

    # Preset resolutions
    preset_cfg = PRESETS.get(preset, PRESETS['tiktok'])
    tw, th = int(preset_cfg['width']), int(preset_cfg['height'])

    # Determine vertical margin
    if tw < th:
        video_h = tw * 9 / 16
        space_below = (th - video_h) / 2
        margin_v = max(int(space_below - 100), style.get('margin_v', 80))
    else:
        margin_v = style.get('margin_v', 80)
    margin_v = max(margin_v, 40)

    bold_flag = -1 if style['bold'] else 0
    default_font = resolve_ass_font(style['font'])
    secondary_font = resolve_ass_font(style.get('secondary_font', default_font))
    hook_font = resolve_ass_font("Montserrat Black")

    ass_header = f"""[Script Info]
Title: Only Clipper Rebuilt Subtitles
ScriptType: v4.00+
PlayResX: {tw}
PlayResY: {th}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{default_font},{style['fontsize']},{style['primary_color']},{style['highlight_color']},{style['outline_color']},{style['back_color']},{bold_flag},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{style['alignment']},40,40,{margin_v},1
Style: Hook,{hook_font},80,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,10,0,8,40,40,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [ass_header]

    # 1. Centered Persistent Headline (first 5 seconds of clip)
    if hook_headline:
        headline_end = format_ass_time(5.0)
        lines.append(f"Dialogue: 0,0:00:00.00,{headline_end},Hook,,0,0,0,,{{\\fad(200,200) \\an8}}{escape_ass_text(hook_headline.upper())}\n")

    # 2. Add Word Captions
    if clip_words:
        groups = []
        current_group = []

        target_group_size = 2
        if caption_style == "hormozi":
            target_group_size = 1
        elif caption_style == "minimal_modern":
            target_group_size = 3

        for word in clip_words:
            current_group.append(word)
            w_text = word['word'].strip()
            if len(current_group) >= target_group_size or (
                len(current_group) >= 1 and w_text and w_text[-1] in '.!?,;:'
            ):
                groups.append(current_group)
                current_group = []
        if current_group:
            groups.append(current_group)

        for idx, group in enumerate(groups):
            if not group:
                continue

            group_start = group[0]['start'] - clip_start
            group_end = group[-1]['end'] - clip_start

            if group_start < 0:
                group_start = 0.0

            if idx < len(groups) - 1:
                next_start = groups[idx+1][0]['start'] - clip_start
                display_end = min(group_end + (0.35 if caption_style == "minimal_modern" else 0.2), next_start)
            else:
                display_end = group_end + (0.35 if caption_style == "minimal_modern" else 0.2)

            start_ts = format_ass_time(group_start)
            end_ts = format_ass_time(display_end)

            karaoke_parts = []
            emphasis_idx = 1 if caption_style == "minimal_modern" and len(group) > 1 else 0

            for j, word in enumerate(group):
                duration_cs = int((word['end'] - word['start']) * 100)
                if duration_cs < 8:
                    duration_cs = 8

                raw_word = word['word'].strip()
                clean_word = raw_word.lower().strip('.,!?:;"()')

                # Emojis rolling logic
                digest = hashlib.md5(word["word"].encode()).digest()
                roll_val = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
                emoji_rolled = roll_val < 0.3
                emoji_picked = EMOJIS[int.from_bytes(digest[:4], "big") % len(EMOJIS)]

                if caption_style == "typography_motion":
                    if clean_word in POWER_WORDS:
                        display_word = raw_word.upper()
                        if emoji_rolled:
                            display_word += " " + emoji_picked
                        part = f"{{\\fn{default_font}}}{{\\c{style['primary_color']}}}{{\\k{duration_cs}}}{escape_ass_text(display_word)} "
                    else:
                        display_word = raw_word.lower()
                        part = f"{{\\fn{secondary_font}}}{{\\c{style['highlight_color']}}}{{\\k{duration_cs}}}{escape_ass_text(display_word)} "
                elif caption_style == "hormozi":
                    display_word = raw_word.upper()
                    if clean_word in POWER_WORDS and emoji_rolled:
                        display_word += " " + emoji_picked
                    color_tag = style['highlight_color'] if (j % 2 == 0) else style['primary_color']
                    part = f"{{\\c{color_tag}}}{{\\k{duration_cs}}}{escape_ass_text(display_word)} "
                elif caption_style == "minimal_modern":
                    display_word = raw_word.capitalize()
                    color_tag = style['highlight_color'] if j == emphasis_idx else style['primary_color']
                    part = f"{{\\c{color_tag}}}{{\\k{duration_cs}}}{escape_ass_text(display_word)} "
                else:
                    display_word = raw_word.upper()
                    if clean_word in POWER_WORDS and emoji_rolled:
                        display_word += " " + emoji_picked
                    part = f"{{\\k{duration_cs}}}{escape_ass_text(display_word)} "

                karaoke_parts.append(part)

            text = "".join(karaoke_parts).strip()

            if caption_style == "hormozi":
                animation = f"{{\\an{style['alignment']}\\fad(80,80)\\t(0,120,\\fscx110\\fscy110)\\t(120,240,\\fscx100\\fscy100)}}"
            elif caption_style == "minimal_modern":
                animation = f"{{\\an{style['alignment']}\\fad(180,180)}}"
            else:
                animation = f"{{\\an{style['alignment']}\\fad(50,50)\\t(0,80,\\fscx120\\fscy120)\\t(80,160,\\fscx100\\fscy100)}}"

            lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{animation}{text}\n")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return output_path


def create_clip(video_path, clip_info, words, output_path, clip_index,
                progress_callback=None, caption_style=None, preset="tiktok"):
    """
    Renders a single video clip with face tracking, headlines, and karaoke subtitles.
    """
    start = clip_info['start_time']
    end = clip_info['end_time']
    duration = end - start

    preset_cfg = PRESETS.get(preset, PRESETS['tiktok'])
    tw, th = int(preset_cfg['width']), int(preset_cfg['height'])

    # 1. Run Dynamic Speaker Face Tracking
    from services.face_processor import tracker
    if progress_callback:
        progress_callback(f"Running active speaker face tracking for clip {clip_index+1}...", 72 + clip_index * 2)

    tracking = tracker.get_dynamic_crop_coordinates(video_path, start, end, tw, th)

    if progress_callback:
        progress_callback(f"Rendering viral clip {clip_index + 1}: {clip_info['title']}...", 73 + clip_index * 2)

    # 2. Generate ASS subtitle files
    work_dir = os.path.dirname(output_path)
    ass_path = os.path.join(work_dir, f"subs_{clip_index}.ass")
    hook_headline = clip_info.get('hook_caption', clip_info['title'])
    generate_ass_subtitles(words, start, end, ass_path, caption_style, preset, hook_headline)

    # Escape paths for FFmpeg filters
    ass_escaped = ass_path.replace('\\', '/').replace(':', '\\:')
    src_w, src_h, _ = get_video_info(video_path)

    # 3. Formulate Filter Chains
    if tracking and preset in ("tiktok", "youtube_shorts"):
        cw = tracking['crop_w']
        ch = tracking['crop_h']

        centers = list(tracking['coords'].values())
        median_x = sorted(centers)[len(centers) // 2]
        crop_x = max(0, min(int(median_x - (cw / 2)), src_w - cw))

        filter_complex = (
            f"[0:v]crop={cw}:{ch}:{crop_x}:0,"
            f"scale={tw}:{th}[vid];"
            f"[vid]ass='{ass_escaped}'[out]"
        )
    else:
        # Standard rendering without dynamic face tracking
        source_ar = src_w / src_h
        target_ar = tw / th
        if abs(source_ar - target_ar) > 0.05:
            # Aspect ratio mismatch: use professional blurred background overlay
            filter_complex = (
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th},boxblur=25:5[bg];"
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vid];"
                f"[vid]ass='{ass_escaped}'[out]"
            )
        else:
            # Aspect ratios match: direct scale to avoid processing overhead
            filter_complex = (
                f"[0:v]scale={tw}:{th}[vid];"
                f"[vid]ass='{ass_escaped}'[out]"
            )

    cmd = [
        'ffmpeg',
        '-ss', str(start),
        '-i', video_path,
        '-t', str(duration),
        '-filter_complex', filter_complex,
        '-map', '[out]',
        '-map', '0:a?',
        '-c:v', 'libx264',
        '-preset', 'superfast',
        '-crf', '20',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '160k',
        '-y',
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg process returned code {result.returncode}: {result.stderr[-400:]}")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"FFmpeg render timed out after {FFMPEG_TIMEOUT_SECONDS}s") from exc

    return output_path


def safe_create_clip(video_path, clip_info, words, output_path, clip_index,
                      progress_callback=None, caption_style=None, preset="tiktok"):
    """
    Fault-tolerant rendering wrapper.
    Falls back cleanly to static center crop if MediaPipe/dynamic crops fail.
    """
    try:
        create_clip(
            video_path=video_path,
            clip_info=clip_info,
            words=words,
            output_path=output_path,
            clip_index=clip_index,
            progress_callback=progress_callback,
            caption_style=caption_style,
            preset=preset,
        )
        return {"ok": True, "attempt": "dynamic"}
    except Exception as exc:
        logger.warning("Dynamic speaker track rendering failed for clip %d. Falling back to static center crop. Error: %s",
                       clip_index + 1, exc)

    # Static Fallback Crop Execution
    try:
        start = clip_info['start_time']
        end = clip_info['end_time']
        duration = end - start

        preset_cfg = PRESETS.get(preset, PRESETS['tiktok'])
        tw, th = int(preset_cfg['width']), int(preset_cfg['height'])

        work_dir = os.path.dirname(output_path)
        ass_path = os.path.join(work_dir, f"subs_{clip_index}.ass")

        # Regenerate ASS if deleted or missing
        if not os.path.exists(ass_path):
            hook_headline = clip_info.get('hook_caption', clip_info['title'])
            generate_ass_subtitles(words, start, end, ass_path, caption_style, preset, hook_headline)

        ass_escaped = ass_path.replace('\\', '/').replace(':', '\\:')
        src_w, src_h, _ = get_video_info(video_path)

        # Mathematically robust center crop fallback for any source/target aspect ratios
        target_ar = tw / th
        source_ar = src_w / src_h

        if source_ar > target_ar:
            # Source is wider than target -> crop width
            crop_h = src_h
            crop_w = int(src_h * target_ar)
            crop_x = (src_w - crop_w) // 2
            crop_y = 0
        else:
            # Source is taller than target -> crop height
            crop_w = src_w
            crop_h = int(src_w / target_ar)
            crop_x = 0
            crop_y = (src_h - crop_h) // 2

        filter_complex = (
            f"[0:v]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={tw}:{th}[vid];"
            f"[vid]ass='{ass_escaped}'[out]"
        )

        cmd = [
            'ffmpeg', '-ss', str(start), '-i', video_path,
            '-t', str(duration), '-filter_complex', filter_complex,
            '-map', '[out]', '-map', '0:a?',
            '-c:v', 'libx264', '-preset', 'superfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
            '-y', output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SECONDS)
        if result.returncode != 0:
            return {"ok": False, "error": f"Static fallback crop failed: {result.stderr[-300:]}"}

        return {"ok": True, "attempt": "static_fallback"}
    except Exception as exc:
        logger.error("All rendering options exhausted. Render failed for clip %d. Error: %s", clip_index + 1, exc)
        return {"ok": False, "error": str(exc)}
