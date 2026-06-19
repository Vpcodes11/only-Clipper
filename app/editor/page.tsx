"use client";

import React, { useState, useEffect, useRef, useMemo, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Sparkles,
  Play,
  Pause,
  Save,
  RotateCcw,
  Video,
  Type,
  Sliders,
  ChevronLeft,
  Loader2,
  Tv,
  ExternalLink,
  AlertTriangle,
} from "lucide-react";

interface Word {
  word: string;
  start: number;
  end: number;
}

interface Clip {
  id?: string;
  clip_id?: string;
  filename: string;
  title: string;
  virality_score: number;
  duration?: string | number;
  hook_caption?: string;
  words?: Word[];
  url?: string;
  thumbnail_url?: string;
  render_version?: number;
  start_time: number;
  end_time: number;
}

export default function EditorPageWrapper() {
  return (
    <Suspense fallback={
      <div className="editor-loading-screen">
        <Loader2 size={32} className="spin text-cyan-400" />
        <p>Loading editor environment...</p>
      </div>
    }>
      <EditorPage />
    </Suspense>
  );
}

function EditorPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const jobId = searchParams.get("job");

  const [job, setJob] = useState<any>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [selectedClipIndex, setSelectedClipIndex] = useState<number>(0);
  
  const [words, setWords] = useState<Word[]>([]);
  const [title, setTitle] = useState("");
  const [hookCaption, setHookCaption] = useState("");
  const [captionStyle, setCaptionStyle] = useState("typography_motion");
  const [preset, setPreset] = useState("tiktok");

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [showSafeZones, setShowSafeZones] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [activeWordIdx, setActiveWordIdx] = useState<number | null>(null);
  const [editingWordIdx, setEditingWordIdx] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const pollTimerRef = useRef<any>(null);
  const isMountedRef = useRef(true);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

  // Fetch job state from backend
  const fetchJobDetails = useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await fetch(`${apiUrl}/api/status/${jobId}`);
      if (res.ok) {
        const data = await res.json();
        setJob(data);
        if (data.clips && data.clips.length > 0) {
          setClips(data.clips);
          // If no clip is currently selected, select the first one
          if (!selectedClip) {
            const initialClip = data.clips[0];
            setSelectedClip(initialClip);
            setSelectedClipIndex(0);
            setTitle(initialClip.title || "");
            setHookCaption(initialClip.hook_caption || initialClip.title || "");
            setWords(JSON.parse(JSON.stringify(initialClip.words || [])));
          } else {
            // Update the selected clip data from the fresh list (keep edits if not saving)
            const activeKey = selectedClip.clip_id || selectedClip.id || selectedClip.filename;
            const freshActive = data.clips.find((c: any) => (c.clip_id || c.id || c.filename) === activeKey);
            if (freshActive && !isSaving) {
              setSelectedClip(freshActive);
              // Only reset words from backend if not currently editing them
              if (editingWordIdx === null) {
                setWords(JSON.parse(JSON.stringify(freshActive.words || [])));
              }
            }
          }
        }
      } else {
        setErrorMsg("Failed to retrieve project detail. Check backend server.");
      }
    } catch (e) {
      console.error("Failed to load project:", e);
      setErrorMsg("Failed to load project database. Make sure API is running.");
    } finally {
      setIsLoading(false);
    }
  }, [jobId, selectedClip, isSaving, editingWordIdx, apiUrl]);

  useEffect(() => {
    isMountedRef.current = true;
    fetchJobDetails();
    return () => {
      isMountedRef.current = false;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [jobId]);

  // Sync video time playback with active word subtitles highlight
  useEffect(() => {
    if (!selectedClip || !isPlaying) return;

    const interval = setInterval(() => {
      if (videoRef.current) {
        const time = videoRef.current.currentTime;
        setCurrentTime(time);
        
        const globalTime = selectedClip.start_time + time;
        const matchedIdx = words.findIndex(
          (w) => globalTime >= w.start && globalTime <= w.end
        );
        setActiveWordIdx(matchedIdx !== -1 ? matchedIdx : null);
      }
    }, 100);

    return () => clearInterval(interval);
  }, [isPlaying, words, selectedClip]);

  const selectClip = (clip: Clip, idx: number) => {
    setSelectedClip(clip);
    setSelectedClipIndex(idx);
    setTitle(clip.title || "");
    setHookCaption(clip.hook_caption || clip.title || "");
    setWords(JSON.parse(JSON.stringify(clip.words || [])));
    setIsPlaying(false);
    setCurrentTime(0);
    setActiveWordIdx(null);
    setEditingWordIdx(null);
    if (videoRef.current) {
      videoRef.current.load();
    }
  };

  const handlePlayPause = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
        setIsPlaying(false);
      } else {
        videoRef.current.play();
        setIsPlaying(true);
      }
    }
  };

  const handleWordClick = (word: Word) => {
    if (videoRef.current && selectedClip) {
      const relativeStart = Math.max(0, word.start - selectedClip.start_time);
      videoRef.current.currentTime = relativeStart;
      setCurrentTime(relativeStart);
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleWordTextChange = (idx: number, newText: string) => {
    const updated = [...words];
    updated[idx].word = newText;
    setWords(updated);
  };

  const handleSaveAndRender = async () => {
    if (!selectedClip || !jobId) return;
    setIsSaving(true);
    setErrorMsg(null);

    try {
      const response = await fetch(`${apiUrl}/api/clip/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          clip_id: selectedClip.clip_id || selectedClip.id,
          filename: selectedClip.filename,
          title: title,
          hook_caption: hookCaption,
          words: words,
          caption_style: captionStyle,
          preset: preset,
        }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "Failed to submit clip re-compile request.");
      }

      // Start polling for re-render completion
      let attempts = 0;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      
      pollTimerRef.current = setInterval(async () => {
        attempts += 1;
        if (!isMountedRef.current) {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
          return;
        }
        try {
          const statusRes = await fetch(`${apiUrl}/api/status/${jobId}`);
          if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === "complete") {
              clearInterval(pollTimerRef.current);
              pollTimerRef.current = null;
              
              // Complete re-render, fetch fresh parameters
              const activeKey = selectedClip.clip_id || selectedClip.id || selectedClip.filename;
              const updatedClip = statusData.clips.find((c: any) => (c.clip_id || c.id || c.filename) === activeKey);
              setClips(statusData.clips);
              if (updatedClip) {
                setSelectedClip(updatedClip);
                setWords(JSON.parse(JSON.stringify(updatedClip.words || [])));
              }
              setIsSaving(false);
              if (videoRef.current) {
                videoRef.current.load();
              }
            } else if (statusData.status === "error") {
              clearInterval(pollTimerRef.current);
              pollTimerRef.current = null;
              setIsSaving(false);
              setErrorMsg("Pipeline failed during caption re-rendering. Check backend terminal.");
            }
          }
          if (attempts >= 90) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
            setIsSaving(false);
            setErrorMsg("Re-render is taking longer than expected. Refresh the editor panel.");
          }
        } catch (err) {
          console.error("Polling error:", err);
        }
      }, 2000);

    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || "Failed to submit caption edits.");
      setIsSaving(false);
    }
  };

  const previewSrc = selectedClip?.url
    ? `${selectedClip.url}${selectedClip.url.includes("?") ? "&" : "?"}v=${selectedClip.render_version || 0}`
    : "";

  const clipDuration = selectedClip ? selectedClip.end_time - selectedClip.start_time : 10;

  if (!jobId) {
    return (
      <div className="editor-error-panel">
        <h2>Missing Project Reference</h2>
        <p>No project ID was provided. Return to the dashboard catalog.</p>
        <Link href="/dashboard" className="btn btn-secondary">
          Return to Dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="editor-root animate-fade">
      {/* Loading Overlay */}
      {isSaving && (
        <div className="render-overlay">
          <div className="premium-panel render-card">
            <Loader2 size={40} className="spin text-cyan-400" />
            <h2>Re-compiling Captions...</h2>
            <p>FFmpeg is compiling your custom style layouts directly into the mp4 canvas.</p>
          </div>
        </div>
      )}

      <header className="editor-nav-header">
        <Link href="/dashboard" className="back-link">
          <ChevronLeft size={16} />
          <span>Dashboard</span>
        </Link>
        <div className="header-title">
          <Sparkles size={18} className="text-primary pulse-glow" />
          <h1>Only Clipper Studio</h1>
          {job && <span className="project-badge">{job.source}</span>}
        </div>
      </header>

      {errorMsg && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {isLoading ? (
        <div className="loading-card">
          <Loader2 size={32} className="spin text-cyan-400" />
          <p>Assembling editor elements...</p>
        </div>
      ) : clips.length === 0 ? (
        <div className="empty-state">
          <h2>No Clips Available</h2>
          <p>Make sure this job has completed processing first.</p>
          <Link href="/dashboard" className="btn btn-primary">Return to Dashboard</Link>
        </div>
      ) : (
        <div className="editor-workspace">
          {/* 1. Sidebar list of clips */}
          <aside className="premium-panel clips-sidebar">
            <div className="sidebar-header">
              <h2>Viral Clips</h2>
              <span className="clips-count">{clips.length} Short{clips.length !== 1 ? "s" : ""}</span>
            </div>
            <div className="clips-list-scroll">
              {clips.map((clip, index) => {
                const clipKey = clip.clip_id || clip.id || clip.filename;
                const isActive = (selectedClip?.clip_id || selectedClip?.id || selectedClip?.filename) === clipKey;
                return (
                  <div
                    key={clipKey}
                    onClick={() => selectClip(clip, index)}
                    className={`clip-item ${isActive ? "active" : ""}`}
                  >
                    <div className="clip-thumb-wrapper">
                      <img
                        src={clip.thumbnail_url || ""}
                        alt={clip.title}
                        className="clip-thumb"
                        onError={(e) => {
                          e.currentTarget.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100'><rect width='100' height='100' fill='%23111'/></svg>";
                        }}
                      />
                      <span className="duration-tag">{clip.duration || Math.round(clip.end_time - clip.start_time)}s</span>
                    </div>
                    <div className="clip-meta">
                      <h3>{clip.title || `Clip #${index+1}`}</h3>
                      <div className="virality-score">
                        <span className="score-label">Virality Score:</span>
                        <span className="score-val">{clip.virality_score?.toFixed(1) || "8.5"}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </aside>

          {/* 2. Middle player column */}
          <div className="player-column">
            <div
              className="premium-panel player-panel"
              style={{
                aspectRatio: preset === "landscape" ? "16/9" : preset === "square" ? "1/1" : "9/16",
                maxHeight: "440px",
                margin: "0 auto",
                transition: "aspect-ratio 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
              }}
            >
              {previewSrc ? (
                <video
                  ref={videoRef}
                  src={previewSrc}
                  className="preview-video"
                  onClick={handlePlayPause}
                  onPlay={() => setIsPlaying(true)}
                  onPause={() => setIsPlaying(false)}
                  onEnded={() => setIsPlaying(false)}
                  onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                />
              ) : (
                <div className="no-video">No preview video loaded</div>
              )}

              {/* Safe zone toggle overlay */}
              <button
                type="button"
                onClick={() => setShowSafeZones(!showSafeZones)}
                className={`safezone-btn ${showSafeZones ? "active" : ""}`}
              >
                <Tv size={14} />
                <span>{showSafeZones ? "Hide Safezones" : "Show Safezones"}</span>
              </button>

              {/* Simulated Safezones */}
              {showSafeZones && (
                <div className="safezone-overlay">
                  <div className="tok-sidebar">
                    <div className="tok-avatar" />
                    <div className="tok-action">❤</div>
                    <div className="tok-action">💬</div>
                    <div className="tok-action">⭐</div>
                  </div>
                  <div className="tok-footer">
                    <span className="tok-user">@onlyclipper.app</span>
                    <span className="tok-desc">AI dynamic caption re-framing overlay</span>
                  </div>
                </div>
              )}

              {/* Controls triggers overlay */}
              <div className="viewport-trigger" onClick={handlePlayPause}>
                {!isPlaying && (
                  <div className="play-btn-large">
                    <Play size={24} fill="#05060d" className="text-black" />
                  </div>
                )}
              </div>
            </div>

            {/* Timeline Waveform Seeker */}
            <div className="premium-panel waveform-panel">
              <div className="waveform-header">
                <span>Timeline Seeker</span>
                <span className="time-display font-mono">
                  {currentTime.toFixed(1)}s / {clipDuration.toFixed(1)}s
                </span>
              </div>
              <div
                className="waveform-seeker"
                onClick={(e) => {
                  if (!videoRef.current) return;
                  const rect = e.currentTarget.getBoundingClientRect();
                  const clickX = e.clientX - rect.left;
                  const ratio = Math.max(0, Math.min(1, clickX / rect.width));
                  const targetTime = ratio * clipDuration;
                  videoRef.current.currentTime = targetTime;
                  setCurrentTime(targetTime);
                }}
              >
                {Array.from({ length: 40 }).map((_, i) => {
                  const barProgressRatio = i / 40;
                  const currentRatio = currentTime / clipDuration;
                  const isActive = barProgressRatio <= currentRatio;
                  
                  const duration = selectedClip ? selectedClip.end_time - selectedClip.start_time : 10;
                  const timeAtBar = (selectedClip?.start_time || 0) + (i / 40) * duration;
                  const isSpoken = words.some(w => timeAtBar >= w.start && timeAtBar <= w.end);
                  
                  const baseHeight = isSpoken ? 50 : 20;
                  const randomNoise = (Math.sin(i * 1.6) + 1) * 8;
                  const barHeight = Math.min(95, baseHeight + randomNoise);

                  return (
                    <div
                      key={i}
                      className={`waveform-bar ${isActive ? "active" : ""} ${isSpoken ? "spoken" : ""}`}
                      style={{ height: `${barHeight}%` }}
                    />
                  );
                })}
              </div>
            </div>

            {/* Design Presets Controls */}
            <div className="premium-panel design-controls">
              <div className="controls-row">
                <div className="control-item">
                  <label>
                    <Type size={14} />
                    <span>Caption Style</span>
                  </label>
                  <select
                    value={captionStyle}
                    onChange={(e) => setCaptionStyle(e.target.value)}
                    className="form-input"
                  >
                    <option value="typography_motion">Typography Motion</option>
                    <option value="hormozi">Hormozi Bold Caps</option>
                    <option value="ali_abdaal">Ali Abdaal Minimal</option>
                    <option value="beast_mode">Beast Mode Giant</option>
                    <option value="stealth_pro">Stealth Pro Purple</option>
                    <option value="viral">Viral Golden Gold</option>
                  </select>
                </div>
                <div className="control-item">
                  <label>
                    <Video size={14} />
                    <span>Canvas Aspect Ratio</span>
                  </label>
                  <select
                    value={preset}
                    onChange={(e) => setPreset(e.target.value)}
                    className="form-input"
                  >
                    <option value="tiktok">Portrait (9:16)</option>
                    <option value="youtube_shorts">YouTube Shorts (9:16)</option>
                    <option value="square">Square (1:1)</option>
                    <option value="landscape">Landscape (16:9)</option>
                  </select>
                </div>
              </div>

              <div className="control-item">
                <label>
                  <Sliders size={14} />
                  <span>Hook Caption (Top Headline Overlay)</span>
                </label>
                <input
                  type="text"
                  value={hookCaption}
                  onChange={(e) => setHookCaption(e.target.value)}
                  placeholder="Paste headline (first 5 seconds of clip)"
                  className="form-input"
                />
              </div>
            </div>
          </div>

          {/* 3. Right transcript column */}
          <div className="premium-panel transcript-column">
            <div className="transcript-header">
              <h2>Interactive Captions</h2>
              <p>Seek video via click · Edit text via double-click</p>
            </div>
            
            <div className="words-grid-wrapper">
              <div className="words-grid">
                {words.map((w, idx) => {
                  const isActive = activeWordIdx === idx;
                  const isEditing = editingWordIdx === idx;
                  
                  return (
                    <div
                      key={idx}
                      onClick={() => handleWordClick(w)}
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        setEditingWordIdx(idx);
                      }}
                      className={`word-card ${isActive ? "active" : ""} ${isEditing ? "editing" : ""}`}
                    >
                      <span className="word-ts font-mono">{w.start.toFixed(1)}s</span>
                      {isEditing ? (
                        <input
                          type="text"
                          value={w.word || ""}
                          onChange={(e) => handleWordTextChange(idx, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              setEditingWordIdx(null);
                            }
                          }}
                          onBlur={() => setEditingWordIdx(null)}
                          className="word-input-edit"
                          autoFocus
                        />
                      ) : (
                        <span className="word-text">{w.word}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="transcript-footer">
              <div className="control-item mb-4">
                <label>Clip Metadata Title</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="form-input"
                />
              </div>
              
              <div className="editor-actions">
                <button
                  type="button"
                  onClick={() => {
                    if (selectedClip) {
                      setWords(JSON.parse(JSON.stringify(selectedClip.words || [])));
                    }
                  }}
                  className="btn btn-secondary"
                  title="Reset edits to baseline"
                >
                  <RotateCcw size={16} />
                  <span>Reset</span>
                </button>
                
                <button
                  type="button"
                  onClick={handleSaveAndRender}
                  disabled={isSaving}
                  className="btn btn-accent btn-flex"
                >
                  <Save size={16} />
                  <span>Save & Compile Clip</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .editor-root {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .editor-loading-screen {
          min-height: 400px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
          color: var(--muted);
        }
        .render-overlay {
          position: fixed;
          top: 0; left: 0; width: 100vw; height: 100vh;
          background: rgba(0,0,0,0.88);
          backdrop-filter: blur(12px);
          z-index: 1500;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
        }
        .render-card {
          padding: 40px;
          text-align: center;
          max-width: 440px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 20px;
        }
        .render-card h2 { font-size: 22px; }
        .render-card p { color: var(--muted); font-size: 14px; }
        
        .editor-nav-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
        }
        .back-link {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          color: var(--muted);
          font-size: 14px;
          text-decoration: none;
          font-weight: 600;
          transition: color 0.2s ease;
        }
        .back-link:hover { color: #ffffff; }
        .header-title {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .header-title h1 { font-size: 24px; }
        .project-badge {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid var(--card-border);
          border-radius: 8px;
          padding: 3px 10px;
          font-size: 12px;
          color: var(--muted);
          max-width: 300px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .error-banner {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.2);
          border-radius: 12px;
          padding: 16px;
          display: flex;
          align-items: center;
          gap: 12px;
          color: #fda4af;
          font-size: 14px;
        }
        .loading-card, .empty-state {
          min-height: 300px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
          color: var(--muted);
        }
        
        .editor-workspace {
          display: grid;
          grid-template-columns: 280px 1fr 340px;
          gap: 24px;
          align-items: start;
        }
        
        /* 1. Sidebar */
        .clips-sidebar {
          display: flex;
          flex-direction: column;
          max-height: 700px;
          overflow: hidden;
        }
        .sidebar-header {
          padding: 20px;
          border-bottom: 1px solid var(--card-border);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .sidebar-header h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; }
        .clips-count { font-size: 12px; color: var(--muted-dark); font-weight: 700; }
        .clips-list-scroll {
          overflow-y: auto;
          display: flex;
          flex-direction: column;
        }
        .clip-item {
          display: flex;
          padding: 14px 20px;
          gap: 14px;
          border-bottom: 1px solid var(--card-border);
          cursor: pointer;
          transition: background 0.2s ease;
        }
        .clip-item:hover { background: rgba(255,255,255,0.02); }
        .clip-item.active { background: rgba(246, 92, 139, 0.05); }
        .clip-thumb-wrapper {
          position: relative;
          width: 56px;
          height: 76px;
          background: #000;
          border-radius: 8px;
          overflow: hidden;
          flex-shrink: 0;
          border: 1px solid var(--card-border);
        }
        .clip-item.active .clip-thumb-wrapper {
          border-color: var(--primary);
        }
        .clip-thumb {
          width: 100%; height: 100%; object-fit: cover;
        }
        .duration-tag {
          position: absolute;
          bottom: 4px; right: 4px;
          background: rgba(0,0,0,0.72);
          border-radius: 4px;
          font-size: 9px; font-weight: 800; font-family: monospace;
          padding: 1px 4px;
        }
        .clip-meta {
          display: flex;
          flex-direction: column;
          justify-content: center;
          gap: 4px;
          min-width: 0;
        }
        .clip-meta h3 {
          font-size: 13px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .virality-score {
          font-size: 11px;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .score-label { color: var(--muted-dark); }
        .score-val { color: var(--secondary); font-weight: 800; }
        
        /* 2. Middle Column */
        .player-column {
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .player-panel {
          background: #000;
          position: relative;
          overflow: hidden;
          width: 100%;
          border-radius: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: inset 0 0 30px rgba(0,0,0,0.85);
        }
        .preview-video { width: 100%; height: 100%; object-fit: contain; }
        .no-video { color: var(--muted-dark); font-size: 14px; }
        
        .safezone-btn {
          position: absolute;
          top: 16px; right: 16px;
          background: rgba(13, 17, 30, 0.7);
          border: 1px solid var(--card-border);
          padding: 8px 12px;
          border-radius: 10px;
          color: #ffffff;
          font-size: 12px;
          font-weight: 700;
          display: flex;
          align-items: center;
          gap: 6px;
          cursor: pointer;
          backdrop-filter: blur(10px);
          transition: all 0.2s ease;
        }
        .safezone-btn:hover { background: rgba(255,255,255,0.1); }
        .safezone-btn.active { border-color: var(--secondary); box-shadow: 0 0 10px var(--secondary-glow); }
        
        .safezone-overlay {
          position: absolute;
          inset: 0;
          pointer-events: none;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 32px 24px;
        }
        .tok-sidebar {
          align-self: flex-end;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 16px;
          margin-top: auto;
          margin-bottom: 24px;
        }
        .tok-avatar {
          width: 32px; height: 32px; border-radius: 50%;
          background: var(--card-border);
          border: 1px solid #ffffff;
        }
        .tok-action { font-size: 20px; text-shadow: 0 1px 4px #000; }
        .tok-footer {
          display: flex;
          flex-direction: column;
          gap: 4px;
          text-shadow: 0 1px 4px #000;
        }
        .tok-user { font-size: 13px; font-weight: 750; }
        .tok-desc { font-size: 11px; color: var(--muted); }

        .viewport-trigger {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        }
        .play-btn-large {
          width: 60px; height: 60px;
          background: #ffffff;
          border-radius: 50%;
          display: grid;
          place-items: center;
          box-shadow: 0 12px 24px rgba(0,0,0,0.5);
          transition: transform 0.2s ease;
        }
        .play-btn-large:hover { transform: scale(1.05); }
        
        .waveform-panel { padding: 20px; }
        .waveform-header {
          display: flex;
          justify-content: space-between;
          font-size: 12px;
          font-weight: 700;
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          margin-bottom: 12px;
        }
        .waveform-seeker {
          height: 60px;
          display: flex;
          align-items: center;
          gap: 3px;
          cursor: pointer;
        }
        .waveform-bar {
          flex: 1;
          background: rgba(255,255,255,0.06);
          border-radius: 99px;
          transition: background 0.2s ease, height 0.2s ease;
        }
        .waveform-bar.spoken { background: rgba(255,255,255,0.18); }
        .waveform-bar.active { background: linear-gradient(180deg, var(--primary), var(--secondary)); }
        
        .design-controls {
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 20px;
        }
        .controls-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        .control-item {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .control-item label {
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--muted);
          display: flex;
          align-items: center;
          gap: 6px;
        }
        
        /* 3. Transcript Column */
        .transcript-column {
          display: flex;
          flex-direction: column;
          max-height: 700px;
          overflow: hidden;
        }
        .transcript-header {
          padding: 20px;
          border-bottom: 1px solid var(--card-border);
        }
        .transcript-header h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; }
        .transcript-header p { font-size: 12px; color: var(--muted); margin-top: 2px; }
        
        .words-grid-wrapper {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
        }
        .words-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
          gap: 10px;
        }
        .word-card {
          background: rgba(255,255,255,0.015);
          border: 1px solid rgba(255,255,255,0.04);
          border-radius: 10px;
          padding: 8px 12px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .word-card:hover {
          background: rgba(255,255,255,0.04);
          border-color: rgba(255,255,255,0.12);
          transform: translateY(-1px);
        }
        .word-card.active {
          background: rgba(6, 182, 212, 0.06);
          border-color: var(--secondary);
          box-shadow: 0 0 12px var(--secondary-glow);
        }
        .word-card.editing {
          border-color: var(--primary);
          background: rgba(246,92,139,0.04);
        }
        .word-ts { font-size: 9px; color: var(--primary); font-weight: 700; }
        .word-text { font-size: 13px; font-weight: 600; text-align: center; }
        .word-input-edit {
          background: rgba(0,0,0,0.3);
          border: 1px solid var(--card-border);
          border-radius: 6px;
          color: #ffffff;
          font-family: inherit;
          font-size: 13px;
          font-weight: 600;
          text-align: center;
          padding: 2px 4px;
          outline: none;
          width: 100%;
        }
        
        .transcript-footer {
          padding: 20px;
          border-top: 1px solid var(--card-border);
          background: rgba(5,6,12,0.3);
        }
        .mb-4 { margin-bottom: 16px; }
        .editor-actions {
          display: grid;
          grid-template-columns: auto 1fr;
          gap: 12px;
        }
        .btn-flex {
          display: flex;
          flex-grow: 1;
        }
        
        @media (max-width: 1100px) {
          .editor-workspace {
            grid-template-columns: 1fr;
          }
          .clips-sidebar { max-height: 250px; }
          .transcript-column { max-height: 400px; }
        }
      `}</style>
    </div>
  );
}
