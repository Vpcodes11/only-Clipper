import logging
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Lazy load model to avoid slow startup times
_model = None

def get_embedding_model():
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def build_blocks(enriched_segments, block_duration=15.0):
    """
    Groups granular segments into coherent blocks of roughly `block_duration` seconds.
    """
    blocks = []
    if not enriched_segments:
        return blocks
        
    current_block = {
        "start": enriched_segments[0]["start"],
        "end": enriched_segments[0]["end"],
        "text": enriched_segments[0]["text"],
        "segments": [enriched_segments[0]]
    }
    
    for seg in enriched_segments[1:]:
        dur = current_block["end"] - current_block["start"]
        # If we reach target block duration, or if there's a huge pause (>3s), cut a block
        if dur >= block_duration or (seg["start"] - current_block["end"] > 3.0):
            blocks.append(current_block)
            current_block = {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "segments": [seg]
            }
        else:
            current_block["end"] = seg["end"]
            current_block["text"] += " " + seg["text"]
            current_block["segments"].append(seg)
            
    if current_block["segments"]:
        blocks.append(current_block)
        
    return blocks

def detect_semantic_boundaries(blocks, similarity_threshold=0.5):
    """
    Returns indices of blocks that start a new scene.
    """
    if len(blocks) < 2:
        return [0]
        
    model = get_embedding_model()
    texts = [b["text"] for b in blocks]
    embeddings = model.encode(texts)
    
    boundaries = [0]
    similarities = []
    
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity([embeddings[i]], [embeddings[i+1]])[0][0]
        similarities.append(sim)
        
        # Calculate dynamic threshold based on local context
        # If similarity drops significantly below a threshold, mark as boundary
        if sim < similarity_threshold:
            # Check for pauses to reinforce boundary
            gap = blocks[i+1]["start"] - blocks[i]["end"]
            if gap > 1.0 or sim < similarity_threshold - 0.1: 
                boundaries.append(i + 1)
                
    return boundaries

def construct_scenes(blocks, boundaries, max_words=400):
    """
    Groups blocks into scenes, applies context stitching, and enforces token guardrails.
    """
    scenes = []
    
    for i in range(len(boundaries)):
        start_idx = boundaries[i]
        end_idx = boundaries[i+1] if i + 1 < len(boundaries) else len(blocks)
        
        scene_blocks = blocks[start_idx:end_idx]
        
        # Enforce token guardrails
        split_scenes = []
        current_split = []
        current_words = 0
        
        for block in scene_blocks:
            words = len(block["text"].split())
            if current_words + words > max_words and current_split:
                split_scenes.append(current_split)
                current_split = [block]
                current_words = words
            else:
                current_split.append(block)
                current_words += words
                
        if current_split:
            split_scenes.append(current_split)
            
        for split in split_scenes:
            scenes.append(split)
            
    # Apply context stitching
    stitched_scenes = []
    for i, scene in enumerate(scenes):
        stitched_scene = list(scene)

        # Add 1 segment of previous context (not full block)
        if i > 0 and scenes[i-1]:
            prev_block = scenes[i-1][-1]
            prev_segs = prev_block["segments"]
            # Take last 1-2 segments for brief context
            if len(prev_segs) >= 2:
                stitched_scene.insert(0, {"segments": prev_segs[-2:]})
            elif prev_segs:
                stitched_scene.insert(0, {"segments": prev_segs[-1:]})

        # Add 1 segment of next context (not full block)
        if i < len(scenes) - 1 and scenes[i+1]:
            next_block = scenes[i+1][0]
            next_segs = next_block["segments"]
            # Take first 1-2 segments for brief context
            if len(next_segs) >= 2:
                stitched_scene.append({"segments": next_segs[:2]})
            elif next_segs:
                stitched_scene.append({"segments": next_segs[:1]})

        # Flatten back into segments
        scene_segments = []
        for block in stitched_scene:
            scene_segments.extend(block["segments"])

        # Deduplicate segments (since stitching can cause overlaps)
        unique_segments = []
        seen = set()
        for seg in scene_segments:
            if seg["start"] not in seen:
                unique_segments.append(seg)
                seen.add(seg["start"])

        unique_segments.sort(key=lambda x: x["start"])
        stitched_scenes.append(unique_segments)

    return stitched_scenes

def segment_transcript_semantically(enriched_segments, max_words=400):
    """
    Main entry point for semantic segmentation.
    Replaces rigid chunking with adaptive, topic-aware scenes.
    """
    if not enriched_segments:
        return []
        
    blocks = build_blocks(enriched_segments)
    boundaries = detect_semantic_boundaries(blocks)
    scenes = construct_scenes(blocks, boundaries, max_words=max_words)
    
    logger.info("Semantic segmentation produced %d scenes from %d segments", len(scenes), len(enriched_segments))
    return scenes
