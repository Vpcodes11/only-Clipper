"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Search, Download, Trash2, Archive, RefreshCw, Loader2,
  Play, Clock, BarChart3, Grid3X3, List, SlidersHorizontal,
  AlertTriangle, CheckCircle2, Copy, ExternalLink, Film,
} from "lucide-react";

interface ClipData {
  id: string;
  job_id: string;
  filename: string;
  title: string;
  hook_caption?: string;
  virality_score: number;
  reason?: string;
  category?: string;
  hashtags?: string[];
  start_time: number;
  end_time: number;
  duration: number;
  status: string;
  render_version: number;
  url?: string;
  thumbnail_url?: string;
  created_at?: string;
}

interface ClipListResponse {
  clips: ClipData[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  active: { label: "Active", cls: "pill-active" },
  archived: { label: "Archived", cls: "pill-archived" },
  deleted: { label: "Deleted", cls: "pill-error" },
};

function formatDuration(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function ClipLibrary() {
  const [clips, setClips] = useState<ClipData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("active");
  const [sort, setSort] = useState("created_at_desc");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [previewClip, setPreviewClip] = useState<ClipData | null>(null);
  const [actionClipId, setActionClipId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const perPage = 20;

  const fetchClips = useCallback(async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const params = new URLSearchParams({
        page: String(page),
        per_page: String(perPage),
        status: statusFilter,
        sort,
      });
      if (search) params.set("search", search);
      const res = await fetch(`${apiUrl}/api/clips?${params}`);
      if (!res.ok) throw new Error("Failed to load clips");
      const data: ClipListResponse = await res.json();
      setClips(data.clips);
      setTotal(data.total);
      setTotalPages(data.pages);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to load clip library");
    } finally {
      setIsLoading(false);
    }
  }, [page, statusFilter, sort, search]);

  useEffect(() => {
    fetchClips();
  }, [fetchClips]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const handleAction = async (clipId: string, action: string, method: string) => {
    setActionClipId(clipId);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/clips/${clipId}/${action}`, { method });
      if (res.ok) {
        setClips((prev) => prev.map((c) =>
          c.id === clipId ? { ...c, status: action === "archive" ? "archived" : action === "restore" ? "active" : "deleted" } : c
        ));
      }
    } catch (err) {
      console.error(`${action} failed:`, err);
    } finally {
      setActionClipId(null);
    }
  };

  return (
    <div className="clip-library-root">
      <header className="library-header">
        <div>
          <h1>Clip Library</h1>
          <p className="subtitle">{total} clip{total !== 1 ? "s" : ""} · Page {page} of {totalPages}</p>
        </div>
        <div className="header-actions">
          <div className="search-bar">
            <Search size={16} />
            <input
              value={searchInput}
              onChange={(e) => { setSearchInput(e.target.value); setPage(1); }}
              placeholder="Search clips..."
            />
          </div>
        </div>
      </header>

      <section className="toolbar">
        <div className="filter-tabs">
          {["active", "archived", "all"].map((s) => (
            <button
              key={s}
              className={`filter-tab ${statusFilter === s ? "active" : ""}`}
              onClick={() => { setStatusFilter(s); setPage(1); }}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
        <div className="toolbar-right">
          <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} className="sort-select">
            <option value="created_at_desc">Newest</option>
            <option value="created_at_asc">Oldest</option>
            <option value="virality_score_desc">Highest Score</option>
            <option value="duration_asc">Shortest</option>
          </select>
          <div className="view-toggle">
            <button className={`view-btn ${viewMode === "grid" ? "active" : ""}`} onClick={() => setViewMode("grid")}>
              <Grid3X3 size={16} />
            </button>
            <button className={`view-btn ${viewMode === "list" ? "active" : ""}`} onClick={() => setViewMode("list")}>
              <List size={16} />
            </button>
          </div>
        </div>
      </section>

      {errorMsg && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <span>{errorMsg}</span>
        </div>
      )}

      {isLoading && clips.length === 0 ? (
        <div className="loading-card">
          <Loader2 size={32} className="spin text-cyan-400" />
          <p>Loading clips...</p>
        </div>
      ) : clips.length === 0 ? (
        <div className="empty-state">
          <Film size={40} className="text-cyan-400" />
          <h2>No Clips Found</h2>
          <p>Upload a video to start generating clips.</p>
          <Link href="/upload" className="btn btn-primary">Upload Video</Link>
        </div>
      ) : viewMode === "grid" ? (
        <div className="clip-grid">
          {clips.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              onAction={handleAction}
              actionClipId={actionClipId}
              onPreview={setPreviewClip}
            />
          ))}
        </div>
      ) : (
        <div className="clip-list">
          {clips.map((clip) => (
            <ClipRow
              key={clip.id}
              clip={clip}
              onAction={handleAction}
              actionClipId={actionClipId}
              onPreview={setPreviewClip}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="btn btn-page">
            Previous
          </button>
          <span className="page-info">Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="btn btn-page">
            Next
          </button>
        </div>
      )}

      {previewClip && (
        <PreviewModal clip={previewClip} onClose={() => setPreviewClip(null)} />
      )}

      <style jsx>{`
        .clip-library-root { display: flex; flex-direction: column; gap: 24px; }
        .library-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
        .subtitle { color: var(--muted); margin-top: 4px; }
        .header-actions { display: flex; align-items: center; gap: 12px; }
        .search-bar { background: rgba(255,255,255,0.04); border: 1px solid var(--card-border); border-radius: 12px; padding: 0 16px; display: flex; align-items: center; gap: 10px; height: 40px; color: var(--muted); min-width: 240px; }
        .search-bar input { background: transparent; border: 0; outline: none; color: #ffffff; font-size: 14px; width: 100%; }
        .toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; }
        .filter-tabs { display: flex; gap: 4px; background: rgba(255,255,255,0.03); border-radius: 12px; padding: 4px; border: 1px solid var(--card-border); }
        .filter-tab { padding: 8px 16px; border-radius: 8px; border: 0; background: transparent; color: var(--muted); font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
        .filter-tab.active { background: var(--primary); color: #ffffff; }
        .toolbar-right { display: flex; align-items: center; gap: 12px; }
        .sort-select { background: rgba(255,255,255,0.04); border: 1px solid var(--card-border); border-radius: 10px; padding: 8px 12px; color: #ffffff; font-size: 13px; outline: none; cursor: pointer; }
        .sort-select option { background: #1a1d2e; color: #fff; }
        .view-toggle { display: flex; border: 1px solid var(--card-border); border-radius: 10px; overflow: hidden; }
        .view-btn { padding: 8px 10px; border: 0; background: transparent; color: var(--muted); cursor: pointer; transition: all 0.15s; display: grid; place-items: center; }
        .view-btn.active { background: rgba(255,255,255,0.08); color: #ffffff; }
        .error-banner { background: rgba(244,63,94,0.1); border: 1px solid rgba(244,63,94,0.2); border-radius: 12px; padding: 16px; display: flex; align-items: center; gap: 12px; color: #fda4af; font-size: 14px; }
        .loading-card { min-height: 300px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; color: var(--muted); }
        .empty-state { min-height: 300px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; border: 1px dashed var(--card-border); border-radius: 24px; }
        .clip-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
        .clip-list { display: flex; flex-direction: column; border: 1px solid var(--card-border); border-radius: 16px; overflow: hidden; }
        .pagination { display: flex; justify-content: center; align-items: center; gap: 16px; padding: 16px 0; }
        .page-info { color: var(--muted); font-size: 13px; }
        .btn-page { padding: 8px 20px; border-radius: 10px; font-size: 13px; border: 1px solid var(--card-border); background: transparent; color: #ffffff; cursor: pointer; }
        .btn-page:disabled { opacity: 0.3; cursor: default; }
      `}</style>
    </div>
  );
}


function ClipCard({ clip, onAction, actionClipId, onPreview }: {
  clip: ClipData;
  onAction: (id: string, action: string, method: string) => void;
  actionClipId: string | null;
  onPreview: (clip: ClipData) => void;
}) {
  const isBusy = actionClipId === clip.id;
  const statusInfo = STATUS_LABELS[clip.status] || { label: clip.status, cls: "" };

  return (
    <div className={`clip-card ${clip.status}`}>
      <div className="card-thumbnail" onClick={() => clip.url && onPreview(clip)}>
        {clip.thumbnail_url ? (
          <img src={clip.thumbnail_url} alt={clip.title} loading="lazy" />
        ) : (
          <div className="thumb-placeholder">
            <Film size={32} />
          </div>
        )}
        {clip.url && (
          <div className="play-overlay">
            <Play size={24} />
          </div>
        )}
        <span className={`status-badge ${statusInfo.cls}`}>{statusInfo.label}</span>
      </div>
      <div className="card-body">
        <h3 className="card-title" title={clip.title}>{clip.title}</h3>
        <div className="card-meta">
          <span><Clock size={12} /> {formatDuration(clip.duration)}</span>
          <span><BarChart3 size={12} /> {clip.virality_score?.toFixed(1)}</span>
          {clip.category && <span className="meta-category">{clip.category}</span>}
        </div>
        <div className="card-actions">
          {clip.url && (
            <a href={clip.url} download={clip.filename} className="icon-btn" title="Download">
              <Download size={14} />
            </a>
          )}
          {clip.status === "active" && (
            <button className="icon-btn" onClick={() => onAction(clip.id, "archive", "POST")} disabled={isBusy} title="Archive">
              {isBusy ? <Loader2 size={14} className="spin" /> : <Archive size={14} />}
            </button>
          )}
          {clip.status === "archived" && (
            <button className="icon-btn" onClick={() => onAction(clip.id, "restore", "POST")} disabled={isBusy} title="Restore">
              <RefreshCw size={14} />
            </button>
          )}
          <button className="icon-btn danger" onClick={() => onAction(clip.id, "", "DELETE")} disabled={isBusy} title="Delete">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <style jsx>{`
        .clip-card { border: 1px solid var(--card-border); border-radius: 16px; overflow: hidden; background: rgba(10,13,22,0.5); transition: border-color 0.2s, transform 0.15s; }
        .clip-card:hover { border-color: rgba(255,255,255,0.12); transform: translateY(-2px); }
        .card-thumbnail { position: relative; width: 100%; aspect-ratio: 9/16; background: #0a0d16; cursor: pointer; overflow: hidden; }
        .card-thumbnail img { width: 100%; height: 100%; object-fit: cover; }
        .thumb-placeholder { width: 100%; height: 100%; display: grid; place-items: center; color: var(--muted); }
        .play-overlay { position: absolute; inset: 0; background: rgba(0,0,0,0.3); display: grid; place-items: center; opacity: 0; transition: opacity 0.2s; }
        .card-thumbnail:hover .play-overlay { opacity: 1; }
        .status-badge { position: absolute; top: 10px; right: 10px; font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 3px 8px; border-radius: 99px; }
        .pill-active { background: rgba(16,185,129,0.15); color: #34d399; }
        .pill-archived { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .pill-error { background: rgba(244,63,94,0.15); color: #fb7185; }
        .card-body { padding: 14px; }
        .card-title { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 10px; }
        .card-meta { display: flex; align-items: center; gap: 12px; font-size: 12px; color: var(--muted); margin-bottom: 12px; }
        .card-meta span { display: flex; align-items: center; gap: 4px; }
        .meta-category { background: rgba(168,85,247,0.1); color: #c084fc; padding: 2px 8px; border-radius: 99px; font-weight: 600; }
        .card-actions { display: flex; gap: 4px; }
        .icon-btn { width: 32px; height: 32px; border-radius: 8px; border: 0; background: rgba(255,255,255,0.04); color: var(--muted); display: grid; place-items: center; cursor: pointer; transition: all 0.15s; text-decoration: none; }
        .icon-btn:hover { background: rgba(255,255,255,0.08); color: #ffffff; }
        .icon-btn.danger:hover { background: rgba(244,63,94,0.1); color: #fb7185; }
      `}</style>
    </div>
  );
}


function ClipRow({ clip, onAction, actionClipId, onPreview }: {
  clip: ClipData;
  onAction: (id: string, action: string, method: string) => void;
  actionClipId: string | null;
  onPreview: (clip: ClipData) => void;
}) {
  const isBusy = actionClipId === clip.id;
  const statusInfo = STATUS_LABELS[clip.status] || { label: clip.status, cls: "" };

  return (
    <div className={`clip-row ${clip.status}`}>
      <div className="row-thumb" onClick={() => clip.url && onPreview(clip)}>
        {clip.thumbnail_url ? (
          <img src={clip.thumbnail_url} alt={clip.title} />
        ) : (
          <div className="thumb-ph"><Film size={18} /></div>
        )}
        {clip.url && <div className="row-play"><Play size={14} /></div>}
      </div>
      <div className="row-info">
        <h4>{clip.title}</h4>
        <div className="row-meta">
          <span>{formatDuration(clip.duration)}</span>
          <span>Score: {clip.virality_score?.toFixed(1)}</span>
          <span className={`row-status ${statusInfo.cls}`}>{statusInfo.label}</span>
          {clip.category && <span className="row-cat">{clip.category}</span>}
        </div>
      </div>
      <div className="row-actions">
        {clip.url && (
          <a href={clip.url} download={clip.filename} className="icon-btn" title="Download">
            <Download size={14} />
          </a>
        )}
        {clip.status === "active" && (
          <button className="icon-btn" onClick={() => onAction(clip.id, "archive", "POST")} disabled={isBusy}>
            {isBusy ? <Loader2 size={14} className="spin" /> : <Archive size={14} />}
          </button>
        )}
        {clip.status === "archived" && (
          <button className="icon-btn" onClick={() => onAction(clip.id, "restore", "POST")} disabled={isBusy}>
            <RefreshCw size={14} />
          </button>
        )}
        <button className="icon-btn danger" onClick={() => onAction(clip.id, "", "DELETE")} disabled={isBusy}>
          <Trash2 size={14} />
        </button>
      </div>
      <style jsx>{`
        .clip-row { display: grid; grid-template-columns: 80px 1fr auto; align-items: center; gap: 16px; padding: 14px 20px; border-top: 1px solid var(--card-border); transition: background 0.15s; }
        .clip-row:first-child { border-top: 0; }
        .clip-row:hover { background: rgba(255,255,255,0.01); }
        .row-thumb { width: 80px; height: 60px; border-radius: 8px; overflow: hidden; background: #0a0d16; cursor: pointer; position: relative; }
        .row-thumb img { width: 100%; height: 100%; object-fit: cover; }
        .thumb-ph { width: 100%; height: 100%; display: grid; place-items: center; color: var(--muted); }
        .row-play { position: absolute; inset: 0; display: grid; place-items: center; background: rgba(0,0,0,0.4); opacity: 0; transition: opacity 0.15s; }
        .row-thumb:hover .row-play { opacity: 1; }
        .row-info h4 { font-size: 14px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
        .row-meta { display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--muted); }
        .row-status { font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 99px; }
        .row-cat { background: rgba(168,85,247,0.1); color: #c084fc; padding: 2px 8px; border-radius: 99px; }
        .row-actions { display: flex; gap: 4px; }
        .icon-btn { width: 32px; height: 32px; border-radius: 8px; border: 0; background: rgba(255,255,255,0.04); color: var(--muted); display: grid; place-items: center; cursor: pointer; transition: all 0.15s; text-decoration: none; }
        .icon-btn:hover { background: rgba(255,255,255,0.08); color: #ffffff; }
        .icon-btn.danger:hover { background: rgba(244,63,94,0.1); color: #fb7185; }
      `}</style>
    </div>
  );
}


function PreviewModal({ clip, onClose }: { clip: ClipData; onClose: () => void }) {
  return (
    <div className="preview-overlay" onClick={onClose}>
      <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
        <button className="close-btn" onClick={onClose}>&times;</button>
        <div className="preview-video">
          {clip.url ? (
            <video src={clip.url} controls autoPlay className="preview-player" />
          ) : (
            <div className="no-preview">
              <Film size={48} />
              <p>Preview unavailable</p>
            </div>
          )}
        </div>
        <div className="preview-info">
          <h3>{clip.title}</h3>
          {clip.hook_caption && <p className="preview-hook">{clip.hook_caption}</p>}
          <div className="preview-meta">
            <span><Clock size={14} /> {formatDuration(clip.duration)}</span>
            <span><BarChart3 size={14} /> Virality: {clip.virality_score?.toFixed(1)}</span>
            {clip.reason && <span className="preview-reason">"{clip.reason}"</span>}
          </div>
          {clip.url && (
            <div className="preview-actions">
              <a href={clip.url} download={clip.filename} className="btn btn-primary">
                <Download size={16} /> Download
              </a>
            </div>
          )}
        </div>
      </div>
      <style jsx>{`
        .preview-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 100; display: grid; place-items: center; padding: 40px; }
        .preview-modal { background: #111322; border: 1px solid var(--card-border); border-radius: 20px; max-width: 800px; width: 100%; max-height: 90vh; overflow-y: auto; position: relative; }
        .close-btn { position: absolute; top: 12px; right: 16px; font-size: 28px; background: none; border: 0; color: var(--muted); cursor: pointer; z-index: 2; }
        .preview-video { background: #000; border-radius: 16px 16px 0 0; overflow: hidden; max-height: 55vh; display: grid; place-items: center; }
        .preview-player { width: 100%; max-height: 55vh; }
        .no-preview { padding: 80px 0; text-align: center; color: var(--muted); display: flex; flex-direction: column; align-items: center; gap: 16px; }
        .preview-info { padding: 24px; }
        .preview-info h3 { font-size: 20px; margin-bottom: 8px; }
        .preview-hook { color: var(--muted); font-size: 14px; margin-bottom: 16px; font-style: italic; }
        .preview-meta { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 20px; }
        .preview-meta span { display: flex; align-items: center; gap: 6px; }
        .preview-reason { color: #a5b4fc; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .preview-actions { display: flex; gap: 12px; }
      `}</style>
    </div>
  );
}
