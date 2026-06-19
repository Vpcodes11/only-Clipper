"use client";

import React, { useEffect, useState } from "react";
import {
  Activity, BarChart3, Brain, CheckCircle2, ChevronDown, ChevronUp,
  Clock3, Download, Eye, Heart, Loader2, RefreshCw, Search,
  Star, ThumbsDown, XCircle,
} from "lucide-react";

interface QAStats {
  total_clips: number;
  clips_with_analytics: number;
  total_views: number;
  total_downloads: number;
  total_favorites: number;
  total_rejects: number;
  total_regenerations: number;
  avg_virality_score: number;
}

interface QAClip {
  id: string;
  title: string;
  hook_caption: string;
  virality_score: number;
  category: string;
  reason: string;
  duration: number;
  context_start: number | null;
  hook_start: number | null;
  payoff_end: number | null;
  judge_provider: string | null;
  judge_model: string | null;
  judge_notes: any;
  psychology_scores: any;
  quality_filter_results: any;
  rejects: number;
  favorites: number;
  user_rating: number | null;
  url: string | null;
}

interface QAJob {
  job_id: string;
  status: string;
  stage: string;
  source: string;
  video_duration: number;
  clips_count: number;
  clips: QAClip[];
  errors: any[];
  stage_timings: any;
  generator_provider: string;
  has_transcript: boolean;
}

interface QAClipDetail {
  clip: any;
  transcript_segment: any;
  analytics: any;
  url: string | null;
}

export default function QADashboard() {
  const [stats, setStats] = useState<QAStats | null>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [jobReview, setJobReview] = useState<QAJob | null>(null);
  const [selectedClip, setSelectedClip] = useState<string | null>(null);
  const [clipDetail, setClipDetail] = useState<QAClipDetail | null>(null);
  const [expandedClip, setExpandedClip] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

  useEffect(() => {
    fetchStats();
    fetchJobs();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch(`${apiUrl}/api/qa/stats`);
      if (res.ok) setStats(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${apiUrl}/api/jobs`);
      if (res.ok) setJobs(await res.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const fetchJobReview = async (jobId: string) => {
    setSelectedJob(jobId);
    setSelectedClip(null);
    setClipDetail(null);
    try {
      const res = await fetch(`${apiUrl}/api/qa/job/${jobId}/review`);
      if (res.ok) setJobReview(await res.json());
    } catch (e) { console.error(e); }
  };

  const fetchClipDetail = async (clipId: string) => {
    setSelectedClip(clipId);
    try {
      const res = await fetch(`${apiUrl}/api/qa/clip/${clipId}`);
      if (res.ok) setClipDetail(await res.json());
    } catch (e) { console.error(e); }
  };

  const ScoreBar = ({ label, value, max = 10, color = "#06b6d4" }: { label: string; value: number; max?: number; color?: string }) => (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div className="score-fill" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} />
      </div>
      <span className="score-value">{typeof value === "number" ? value.toFixed(1) : value}</span>
    </div>
  );

  return (
    <div className="qa-root">
      <header className="qa-header">
        <div>
          <h1><Brain size={24} className="inline mr-2 text-accent" /> QA Dashboard</h1>
          <p className="subtitle">Internal clip quality review, scoring, and behavioral analytics.</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => { fetchStats(); fetchJobs(); }}>
          <RefreshCw size={14} className="mr-1" /> Refresh
        </button>
      </header>

      {/* Stats Overview */}
      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-icon"><BarChart3 size={20} /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_clips}</span>
              <span className="stat-label">Total Clips</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><Activity size={20} /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.avg_virality_score}</span>
              <span className="stat-label">Avg Virality Score</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><Eye size={20} /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_views}</span>
              <span className="stat-label">Total Views</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><Download size={20} /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_downloads}</span>
              <span className="stat-label">Downloads</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><Heart size={20} className="text-rose-400" /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_favorites}</span>
              <span className="stat-label">Favorites</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><ThumbsDown size={20} className="text-amber-400" /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_rejects}</span>
              <span className="stat-label">Rejects</span>
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-icon"><RefreshCw size={20} className="text-purple-400" /></div>
            <div className="stat-body">
              <span className="stat-value">{stats.total_regenerations}</span>
              <span className="stat-label">Regenerations</span>
            </div>
          </div>
        </div>
      )}

      {/* Jobs List */}
      <section className="qa-section">
        <h2>Jobs ({jobs.length})</h2>
        {loading ? (
          <div className="loading"><Loader2 size={24} className="spin" /> Loading...</div>
        ) : (
          <div className="job-grid">
            {jobs.filter((j: any) => j.clips?.length > 0).map((job: any) => (
              <div
                key={job.id}
                className={`job-card ${selectedJob === job.id ? "selected" : ""}`}
                onClick={() => fetchJobReview(job.id)}
              >
                <div className="job-card-header">
                  <span className={`pill pill-${job.status}`}>{job.status}</span>
                  <span className="clips-badge">{job.clips?.length || 0} clips</span>
                </div>
                <p className="job-source">{job.source || `Project ${job.id}`}</p>
                <span className="job-id">{job.id}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Job Review */}
      {jobReview && (
        <section className="qa-section">
          <div className="review-header">
            <h2>Job Review: {jobReview.job_id}</h2>
            <div className="review-meta">
              <span>Generator: {jobReview.generator_provider}</span>
              <span>Duration: {(jobReview.video_duration / 60).toFixed(1)}m</span>
              <span>Clips: {jobReview.clips_count}</span>
              <span>Transcript: {jobReview.has_transcript ? "✅" : "❌"}</span>
            </div>
          </div>

          {jobReview.errors?.length > 0 && (
            <div className="error-panel">
              <h3><XCircle size={16} /> Errors</h3>
              {jobReview.errors.map((err: any, i: number) => (
                <div key={i} className="error-entry">{err.stage}: {err.message}</div>
              ))}
            </div>
          )}

          <div className="clips-table">
            <div className="table-header">
              <span>Clip</span>
              <span>Score</span>
              <span>Category</span>
              <span>Judge</span>
              <span>Feedback</span>
              <span></span>
            </div>
            {jobReview.clips.map((clip: QAClip) => (
              <React.Fragment key={clip.id}>
                <div
                  className={`table-row ${expandedClip === clip.id ? "expanded" : ""}`}
                  onClick={() => {
                    setExpandedClip(expandedClip === clip.id ? null : clip.id);
                    fetchClipDetail(clip.id);
                  }}
                >
                  <div className="clip-title-col">
                    <strong>{clip.title}</strong>
                    <span className="hook-preview">{clip.hook_caption}</span>
                  </div>
                  <span className={`score-badge ${clip.virality_score >= 8 ? "high" : clip.virality_score >= 6 ? "mid" : "low"}`}>
                    {clip.virality_score?.toFixed(1)}
                  </span>
                  <span className="category-tag">{clip.category}</span>
                  <span className="judge-info">
                    {clip.judge_provider || "none"} / {clip.judge_model || "?"}
                  </span>
                  <div className="feedback-icons">
                    {clip.favorites > 0 && <span title="Favorites"><Heart size={12} /> {clip.favorites}</span>}
                    {clip.rejects > 0 && <span title="Rejects"><ThumbsDown size={12} /> {clip.rejects}</span>}
                    {clip.user_rating && <span title="Rating"><Star size={12} /> {clip.user_rating}</span>}
                  </div>
                  <span>{expandedClip === clip.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
                </div>
                {expandedClip === clip.id && clipDetail && (
                  <div className="clip-expansion">
                    <div className="expansion-grid">
                      {/* Transcript */}
                      <div className="expansion-panel">
                        <h4>Transcript Segment</h4>
                        <div className="transcript-box">
                          {clipDetail.transcript_segment?.text || "No transcript available"}
                        </div>
                        <div className="timeline-info">
                          <span>Context: {clip.context_start?.toFixed(1)}s</span>
                          <span>Hook: {clip.hook_start?.toFixed(1)}s</span>
                          <span>Payoff: {clip.payoff_end?.toFixed(1)}s</span>
                          <span>Duration: {clip.duration?.toFixed(1)}s</span>
                        </div>
                      </div>

                      {/* Scores */}
                      <div className="expansion-panel">
                        <h4>Scores & Reasoning</h4>
                        <div className="score-breakdown">
                          <ScoreBar label="Virality" value={clip.virality_score} color="#06b6d4" />
                          {clip.psychology_scores && (
                            <>
                              <ScoreBar label="Curiosity Gap" value={(clip.psychology_scores.curiosity_gap || 0) * 10} color="#a78bfa" />
                              <ScoreBar label="Emotional Contagion" value={(clip.psychology_scores.emotional_contagion || 0) * 10} color="#f472b6" />
                              <ScoreBar label="Payoff Satisfaction" value={(clip.psychology_scores.payoff_satisfaction || 0) * 10} color="#34d399" />
                              <ScoreBar label="Identity Signal" value={(clip.psychology_scores.identity_signal || 0) * 10} color="#fbbf24" />
                              <ScoreBar label="Peak-End Quality" value={(clip.psychology_scores.peak_end_quality || 0) * 10} color="#fb923c" />
                            </>
                          )}
                        </div>
                        <div className="reason-box">
                          <strong>Reason:</strong> {clip.reason}
                        </div>
                      </div>

                      {/* Judge Notes */}
                      <div className="expansion-panel">
                        <h4>Judge & Quality</h4>
                        {clip.judge_notes ? (
                          <pre className="json-preview">{JSON.stringify(clip.judge_notes, null, 2)}</pre>
                        ) : (
                          <p className="muted">No judge notes available</p>
                        )}
                        {clip.quality_filter_results ? (
                          <>
                            <h4 style={{ marginTop: 16 }}>Quality Filters</h4>
                            <pre className="json-preview">{JSON.stringify(clip.quality_filter_results, null, 2)}</pre>
                          </>
                        ) : null}
                      </div>

                      {/* Analytics */}
                      <div className="expansion-panel">
                        <h4>Behavioral Analytics</h4>
                        {clipDetail.analytics ? (
                          <div className="analytics-grid">
                            <div className="analytic-item"><span>Views</span><strong>{clipDetail.analytics.views}</strong></div>
                            <div className="analytic-item"><span>Avg Watch</span><strong>{clipDetail.analytics.avg_watch_ms ? `${(clipDetail.analytics.avg_watch_ms / 1000).toFixed(1)}s` : "N/A"}</strong></div>
                            <div className="analytic-item"><span>Downloads</span><strong>{clipDetail.analytics.downloads}</strong></div>
                            <div className="analytic-item"><span>Favorites</span><strong>{clipDetail.analytics.favorites}</strong></div>
                            <div className="analytic-item"><span>Rejects</span><strong>{clipDetail.analytics.rejects}</strong></div>
                            <div className="analytic-item"><span>Regenerations</span><strong>{clipDetail.analytics.regenerations}</strong></div>
                            <div className="analytic-item"><span>Rating</span><strong>{clipDetail.analytics.user_rating || "N/A"}</strong></div>
                          </div>
                        ) : (
                          <p className="muted">No analytics collected yet</p>
                        )}
                      </div>
                    </div>

                    {/* Video Preview */}
                    {clipDetail.url && (
                      <div className="video-preview">
                        <h4>Rendered Output</h4>
                        <video controls src={clipDetail.url} style={{ width: "100%", maxHeight: 400, borderRadius: 12 }} />
                      </div>
                    )}
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>
        </section>
      )}

      <style jsx>{`
        .qa-root { display: flex; flex-direction: column; gap: 24px; }
        .qa-header { display: flex; justify-content: space-between; align-items: center; }
        .subtitle { color: var(--muted); font-size: 14px; }
        .mr-1 { margin-right: 4px; }
        .mr-2 { margin-right: 8px; }
        .inline { display: inline; vertical-align: middle; }
        .text-accent { color: #a78bfa; }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
        .stat-card { background: rgba(255,255,255,0.03); border: 1px solid var(--card-border); border-radius: 14px; padding: 16px; display: flex; gap: 12px; align-items: center; }
        .stat-icon { color: var(--primary); opacity: 0.7; }
        .stat-body { display: flex; flex-direction: column; }
        .stat-value { font-size: 22px; font-weight: 800; }
        .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }

        .qa-section { background: var(--card); border: 1px solid var(--card-border); border-radius: 20px; padding: 24px; }
        .qa-section h2 { font-size: 16px; margin-bottom: 16px; }

        .job-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
        .job-card { background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 14px; padding: 16px; cursor: pointer; transition: all 0.15s; }
        .job-card:hover { border-color: var(--primary); }
        .job-card.selected { border-color: #a78bfa; background: rgba(168,133,250,0.05); }
        .job-card-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
        .pill { font-size: 10px; font-weight: 800; text-transform: uppercase; padding: 2px 8px; border-radius: 99px; }
        .pill-complete { background: rgba(16,185,129,0.1); color: #34d399; }
        .pill-processing { background: rgba(168,85,247,0.1); color: #c084fc; }
        .pill-error { background: rgba(244,63,94,0.1); color: #fb7185; }
        .clips-badge { font-size: 11px; color: var(--muted); }
        .job-source { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .job-id { font-size: 11px; color: var(--muted-dark); font-family: monospace; }

        .review-header { margin-bottom: 16px; }
        .review-meta { display: flex; gap: 16px; font-size: 12px; color: var(--muted); margin-top: 4px; }

        .error-panel { background: rgba(244,63,94,0.05); border: 1px solid rgba(244,63,94,0.15); border-radius: 12px; padding: 12px; margin-bottom: 16px; }
        .error-panel h3 { font-size: 13px; color: #fb7185; display: flex; align-items: center; gap: 6px; }
        .error-entry { font-size: 11px; font-family: monospace; color: #fda4af; padding: 2px 0; }

        .clips-table { display: flex; flex-direction: column; }
        .table-header { display: grid; grid-template-columns: 2fr 0.8fr 1fr 1.2fr 1fr 0.3fr; gap: 12px; padding: 8px 16px; font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
        .table-row { display: grid; grid-template-columns: 2fr 0.8fr 1fr 1.2fr 1fr 0.3fr; gap: 12px; padding: 12px 16px; border-top: 1px solid var(--card-border); align-items: center; cursor: pointer; transition: background 0.1s; }
        .table-row:hover { background: rgba(255,255,255,0.02); }
        .table-row.expanded { background: rgba(168,133,250,0.05); }
        .clip-title-col { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
        .clip-title-col strong { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .hook-preview { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .score-badge { font-size: 13px; font-weight: 800; padding: 2px 8px; border-radius: 6px; text-align: center; }
        .score-badge.high { background: rgba(16,185,129,0.15); color: #34d399; }
        .score-badge.mid { background: rgba(251,191,36,0.15); color: #fbbf24; }
        .score-badge.low { background: rgba(244,63,94,0.15); color: #fb7185; }
        .category-tag { font-size: 11px; padding: 2px 8px; border-radius: 99px; background: rgba(255,255,255,0.04); color: var(--muted); text-align: center; }
        .judge-info { font-size: 11px; color: var(--muted); font-family: monospace; }
        .feedback-icons { display: flex; gap: 8px; font-size: 11px; color: var(--muted); align-items: center; }

        .clip-expansion { border-top: 1px solid var(--card-border); padding: 20px 16px; background: rgba(0,0,0,0.15); }
        .expansion-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .expansion-panel { background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 12px; padding: 16px; }
        .expansion-panel h4 { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 12px; }
        .transcript-box { font-size: 12px; line-height: 1.6; color: rgba(255,255,255,0.8); max-height: 120px; overflow-y: auto; }
        .timeline-info { display: flex; gap: 12px; margin-top: 8px; font-size: 11px; color: var(--muted); font-family: monospace; }

        .score-breakdown { display: flex; flex-direction: column; gap: 6px; }
        .score-row { display: grid; grid-template-columns: 120px 1fr 40px; gap: 8px; align-items: center; font-size: 11px; }
        .score-label { color: var(--muted); text-align: right; }
        .score-track { height: 6px; background: rgba(255,255,255,0.06); border-radius: 99px; overflow: hidden; }
        .score-fill { height: 100%; border-radius: inherit; transition: width 0.3s ease; }
        .score-value { font-family: monospace; font-weight: 700; }

        .reason-box { margin-top: 12px; font-size: 12px; color: rgba(255,255,255,0.7); background: rgba(255,255,255,0.02); border-radius: 8px; padding: 10px; }
        .reason-box strong { color: var(--primary); }

        .json-preview { font-size: 10px; font-family: monospace; color: #a78bfa; background: rgba(0,0,0,0.3); border-radius: 8px; padding: 10px; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }

        .analytics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .analytic-item { display: flex; justify-content: space-between; padding: 6px 10px; background: rgba(255,255,255,0.02); border-radius: 8px; font-size: 12px; }
        .analytic-item span { color: var(--muted); }
        .analytic-item strong { font-family: monospace; }

        .video-preview { margin-top: 16px; }
        .video-preview h4 { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 8px; }

        .muted { color: var(--muted); font-size: 12px; }
        .loading { display: flex; align-items: center; gap: 8px; color: var(--muted); padding: 40px; justify-content: center; }
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        @media (max-width: 860px) {
          .expansion-grid { grid-template-columns: 1fr; }
          .table-header, .table-row { grid-template-columns: 1.5fr 0.6fr 1fr; }
          .table-header :nth-child(4), .table-row :nth-child(4),
          .table-header :nth-child(5), .table-row :nth-child(5) { display: none; }
        }
      `}</style>
    </div>
  );
}
