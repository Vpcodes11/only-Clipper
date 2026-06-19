"use client";

import React, { useMemo, useRef, useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Loader2,
  Plus,
  Search,
  Trash2,
  UploadCloud,
  ChevronDown,
  ChevronUp,
  Terminal,
  RefreshCw,
} from "lucide-react";

interface Job {
  id: string;
  status: string;
  progress?: number;
  message?: string;
  source?: string;
  clips?: any[];
  stage?: string;
  created_at?: string;
  retry_count?: number;
  max_retries?: number;
  stage_timings?: Record<string, { start: string; end: string; duration_ms: number }>;
  download_quality?: string;
}

const ACTIVE_STATUSES = ["queued", "downloading", "processing"];

const STAGE_MAP: Record<string, { label: string; icon: string }> = {
  job_created: { label: "Initializing", icon: "📋" },
  metadata_fetched: { label: "Analyzing Source", icon: "🔍" },
  download_started: { label: "Downloading", icon: "⬇️" },
  download_completed: { label: "Download Complete", icon: "✅" },
  audio_extracted: { label: "Extracting Audio", icon: "🎵" },
  transcription_completed: { label: "Transcribing", icon: "🗣️" },
  ai_analysis_completed: { label: "Finding Highlights", icon: "🧠" },
  clips_generated: { label: "Clips Identified", icon: "✂️" },
  render_started: { label: "Rendering Clips", icon: "🎬" },
  render_completed: { label: "Render Complete", icon: "🎥" },
  export_completed: { label: "Ready", icon: "🏁" },
  failed: { label: "Failed", icon: "❌" },
  clip_regenerating: { label: "Re-rendering", icon: "🔄" },
  downloading: { label: "Downloading", icon: "⬇️" },
  preflighted: { label: "Analyzing Source", icon: "🔍" },
  transcribed: { label: "Transcribing", icon: "🗣️" },
  analyzed: { label: "Finding Highlights", icon: "🧠" },
  aligned: { label: "Aligning", icon: "📐" },
  clips_rendering: { label: "Rendering", icon: "🎬" },
  clips_rendered: { label: "Render Complete", icon: "🎥" },
  complete: { label: "Ready", icon: "🏁" },
  error: { label: "Error", icon: "❌" },
};

function projectName(job: Job) {
  if (!job.source) return `Project ${job.id}`;
  try {
    const url = new URL(job.source);
    return url.hostname.replace(/^www\./, "") + url.pathname;
  } catch {
    return job.source;
  }
}

function statusLabel(status: string) {
  if (status === "complete") return "Ready";
  if (status === "error") return "Failed";
  if (status === "queued") return "Preparing";
  if (status === "downloading") return "Downloading";
  if (status === "processing") return "Clipping";
  return status;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "complete") return <CheckCircle2 size={18} className="text-emerald-500" />;
  if (status === "error") return <AlertTriangle size={18} className="text-rose-500" />;
  if (ACTIVE_STATUSES.includes(status)) return <Loader2 className="spin text-cyan-400" size={18} />;
  return <Clock3 size={18} className="text-gray-400" />;
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const hasActiveRef = useRef(false);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch(`/api/jobs`);
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
        hasActiveRef.current = data.some((job: Job) => ACTIVE_STATUSES.includes(job.status));
      } else {
        throw new Error("Could not retrieve project database.");
      }
    } catch (err) {
      console.error("Failed to fetch jobs:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(() => {
      if (hasActiveRef.current) {
        fetchJobs();
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const handleDeleteJob = async (jobId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this project? All rendered files will be cleared.")) return;
    setDeletingJobId(jobId);
    setActionError(null);
    try {
      const res = await fetch(`/api/job/${jobId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Could not delete project.");
      setJobs((prev) => prev.filter((job) => job.id !== jobId));
    } catch (err: any) {
      console.error("Failed to delete project:", err);
      setActionError(err.message || "Failed to delete project.");
    } finally {
      setDeletingJobId(null);
    }
  };

  const visibleJobs = useMemo(() => {
    return jobs.filter((job) => {
      const needle = query.trim().toLowerCase();
      if (!needle) return true;
      return `${job.id} ${job.source || ""} ${job.status}`.toLowerCase().includes(needle);
    });
  }, [jobs, query]);

  const readyCount = useMemo(() => jobs.filter((j) => j.status === "complete").length, [jobs]);
  const activeCount = useMemo(() => jobs.filter((j) => ACTIVE_STATUSES.includes(j.status)).length, [jobs]);

  return (
    <div className="dashboard-root">
      <header className="dashboard-header">
        <div>
          <h1>Projects</h1>
          <p className="subtitle">Production clipping engine.</p>
        </div>
        <Link href="/upload" className="btn btn-accent">
          <Plus size={18} />
          Create Video Job
        </Link>
      </header>

      {actionError && (
        <div className="error-banner">
          <AlertTriangle size={18} />
          <span>{actionError}</span>
        </div>
      )}

      {isLoading && jobs.length === 0 ? (
        <div className="loading-card">
          <Loader2 size={32} className="spin text-cyan-400" />
          <p>Loading projects...</p>
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty-state-panel">
          <div className="empty-icon-wrapper">
            <UploadCloud size={40} className="text-cyan-400 pulse-glow" />
          </div>
          <h2>No Projects Found</h2>
          <p>Get started by uploading a video or pasting a URL.</p>
          <div className="empty-actions">
            <Link href="/upload" className="btn btn-primary">Upload Video</Link>
          </div>
        </div>
      ) : (
        <section className="premium-panel projects-section">
          <div className="projects-toolbar">
            <div className="stats-badges">
              <h2>{visibleJobs.length} Project{visibleJobs.length !== 1 ? "s" : ""}</h2>
              {activeCount > 0 && <span className="badge badge-active">{activeCount} Processing</span>}
              {readyCount > 0 && <span className="badge badge-ready">{readyCount} Ready</span>}
            </div>
            <div className="search-bar">
              <Search size={16} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search projects..." />
            </div>
          </div>
          <div className="projects-list">
            {visibleJobs.map((job) => (
              <ProjectRow
                key={job.id}
                job={job}
                onDelete={(id, e) => handleDeleteJob(id, e)}
                deletingJobId={deletingJobId}
                onJobCompleted={fetchJobs}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

interface ProjectRowProps {
  job: Job;
  onDelete: (id: string, e: React.MouseEvent) => void;
  deletingJobId: string | null;
  onJobCompleted: () => void;
}

function ProjectRow({ job, onDelete, deletingJobId, onJobCompleted }: ProjectRowProps) {
  const [localJob, setLocalJob] = useState<Job>(job);
  const [isExpanded, setIsExpanded] = useState(false);
  const [logs, setLogs] = useState<string[]>([job.message || "Checking status..."]);
  const [showLogs, setShowLogs] = useState(true);
  const [resuming, setResuming] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setLocalJob(job);
    if (job.message) {
      setLogs((prev) => {
        if (prev[prev.length - 1] === job.message) return prev;
        return [...prev, job.message!];
      });
    }
  }, [job]);

  useEffect(() => {
    if (!ACTIVE_STATUSES.includes(localJob.status)) return;
    if (wsRef.current) return;

    let isMounted = true;
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/${localJob.id}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      if (!isMounted) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === "progress" || data.type === "stage_start" || data.type === "stage_complete" || data.type === "stage_retry") {
          setLocalJob((prev) => ({
            ...prev,
            progress: data.progress ?? prev.progress,
            message: data.message ?? prev.message,
            stage: data.stage ?? prev.stage,
            status: "processing",
            retry_count: data.retry ?? prev.retry_count,
          }));
          if (data.message) {
            setLogs((prev) => {
              if (prev[prev.length - 1] === data.message) return prev;
              return [...prev, data.message];
            });
          }
        } else if (data.type === "complete") {
          setLocalJob((prev) => ({
            ...prev,
            status: "complete",
            progress: 100,
            message: data.message,
            clips: data.clips || [],
          }));
          setLogs((prev) => [...prev, data.message]);
          onJobCompleted();
        } else if (data.type === "error") {
          setLocalJob((prev) => ({
            ...prev,
            status: "error",
            progress: prev.progress,
            message: data.message,
            stage: data.stage ?? prev.stage,
          }));
          setLogs((prev) => [...prev, `[ERROR] ${data.message}`]);
          onJobCompleted();
        }
      } catch (e) {
        console.error("Failed to parse socket packet:", e);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket closed for job", localJob.id);
    };

    return () => {
      isMounted = false;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [localJob.id, localJob.status, onJobCompleted]);

  useEffect(() => {
    if (isExpanded && showLogs && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, isExpanded, showLogs]);

  const handleResume = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setResuming(true);
    try {
      const res = await fetch(`/api/job/${localJob.id}/resume`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setLocalJob((prev) => ({
          ...prev,
          status: "processing",
          stage: data.stage,
          message: "Resuming...",
        }));
        setLogs((prev) => [...prev, "[Resumed pipeline]"]);
      }
    } catch (err) {
      console.error("Resume failed:", err);
    } finally {
      setResuming(false);
    }
  };

  const progress = Math.max(0, Math.min(100, localJob.progress || (localJob.status === "complete" ? 100 : 0)));
  const stageInfo = STAGE_MAP[localJob.stage || ""] || { label: localJob.stage || "Unknown", icon: "📌" };
  const isFailed = localJob.status === "error" || localJob.stage === "failed";

  const steps = useMemo(() => {
    const defaultSteps = [
      { id: 1, name: "Media Import", desc: "Checking source..." },
      { id: 2, name: "Audio Transcription", desc: "Whisper audio mapping..." },
      { id: 3, name: "Viral Moments Analysis", desc: "LLM virality scoring..." },
      { id: 4, name: "Cut Alignment", desc: "Pause boundary snapping..." },
      { id: 5, name: "Compilation & Rendering", desc: "Dynamic crops & subtitles..." },
    ];
    const status = localJob.status;
    const stage = localJob.stage || "queued";
    let activeIdx = -1;
    if (status === "complete") { activeIdx = 5; }
    else if (status === "error") {
      if (["download_started", "download_completed"].includes(stage)) activeIdx = 0;
      else if (["audio_extracted", "transcription_completed"].includes(stage)) activeIdx = 1;
      else if (["ai_analysis_completed"].includes(stage)) activeIdx = 2;
      else if (["clips_generated"].includes(stage)) activeIdx = 3;
      else activeIdx = 4;
    } else {
      if (["download_started", "download_completed"].includes(stage)) activeIdx = 0;
      else if (["metadata_fetched", "audio_extracted"].includes(stage)) activeIdx = 1;
      else if (["transcription_completed"].includes(stage)) activeIdx = 2;
      else if (["ai_analysis_completed", "clips_generated"].includes(stage)) activeIdx = 3;
      else activeIdx = 4;
    }
    return defaultSteps.map((step, idx) => {
      let stepStatus: "todo" | "active" | "done" | "error" = "todo";
      if (isFailed && idx <= activeIdx) stepStatus = "error";
      else if (idx < activeIdx) stepStatus = "done";
      else if (idx === activeIdx) stepStatus = "active";
      return { ...step, status: stepStatus };
    });
  }, [localJob.status, localJob.stage, isFailed]);

  const expandable = ACTIVE_STATUSES.includes(localJob.status) || isFailed;

  const retryInfo = localJob.retry_count != null && localJob.retry_count > 0
    ? `Retry ${localJob.retry_count}/${localJob.max_retries ?? 3}`
    : null;

  const partialClips = localJob.clips?.length && localJob.stage !== "export_completed";

  return (
    <div className={`project-row-wrapper ${localJob.status}`}>
      <div className="project-row" onClick={() => expandable && setIsExpanded(!isExpanded)}>
        <div className="col-info">
          <div className="status-avatar">
            <StatusIcon status={localJob.status} />
          </div>
          <div className="info-text">
            <h3>
              <span className="stage-icon">{stageInfo.icon}</span>
              {projectName(localJob)}
            </h3>
            <span className="job-id">{localJob.id}</span>
          </div>
        </div>
        <div className="col-stats">
          <span className={`status-pill pill-${localJob.status}`}>
            {isFailed ? "Failed" : stageInfo.label}
          </span>
          {retryInfo && <span className="retry-badge">{retryInfo}</span>}
          <span className="clips-count">
            {localJob.clips?.length || 0} Clip{(localJob.clips?.length || 0) !== 1 ? "s" : ""}
            {partialClips && " ⚡"}
          </span>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
        <div className="col-actions">
          {localJob.status === "complete" && (
            <Link href={`/editor?job=${localJob.id}`} className="btn btn-primary btn-sm">
              Open Editor
            </Link>
          )}
          {isFailed && (
            <button className="btn btn-primary btn-sm resume-btn" onClick={handleResume} disabled={resuming}>
              {resuming ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              Resume
            </button>
          )}
          {expandable && (
            <button className="toggle-btn" type="button">
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          )}
          <button className="delete-btn" onClick={(e) => onDelete(localJob.id, e)} disabled={deletingJobId === localJob.id}>
            {deletingJobId === localJob.id ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
          </button>
        </div>
      </div>

      {isExpanded && expandable && (
        <div className="expansion-panel">
          <div className="panel-layout">
            <div className="checklist-col">
              <h4 className="panel-title">Pipeline Progress</h4>
              <div className="steps-container">
                {steps.map((step, idx) => (
                  <div key={step.id} className={`step-row ${step.status}`}>
                    <div className="step-bullet">
                      <div className={`bullet-circle ${step.status}`}>
                        {step.status === "done" && "✓"}
                        {step.status === "active" && <span className="active-dot" />}
                        {step.status === "error" && "!"}
                        {step.status === "todo" && "•"}
                      </div>
                      {idx < steps.length - 1 && <div className={`bullet-line ${step.status === "done" ? "done" : ""}`} />}
                    </div>
                    <div className="step-details">
                      <span className="step-name">{step.name}</span>
                      <span className="step-desc">{step.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
              {localJob.stage_timings && Object.keys(localJob.stage_timings).length > 0 && (
                <div className="timings-section">
                  <h4 className="panel-title" style={{ marginTop: 20 }}>Stage Timings</h4>
                  {Object.entries(localJob.stage_timings).map(([stage, t]) => (
                    <div key={stage} className="timing-row">
                      <span className="timing-stage">{stage.replace(/_/g, " ")}</span>
                      <span className="timing-duration">{(t.duration_ms / 1000).toFixed(1)}s</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {showLogs && (
              <div className="console-col">
                <div className="console-header">
                  <h4 className="panel-title flex-items">
                    <Terminal size={14} className="text-primary mr-2" />
                    Console Output{isFailed ? ` (${localJob.stage})` : ""}
                  </h4>
                </div>
                <div className="console-terminal">
                  {logs.map((log, index) => (
                    <div key={index} className="log-line">
                      <span className="log-arrow">&gt;</span> {log}
                    </div>
                  ))}
                  <div ref={logEndRef} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
