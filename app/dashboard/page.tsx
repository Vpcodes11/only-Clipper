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
}

const ACTIVE_STATUSES = ["queued", "downloading", "processing"];

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
  if (status === "queued") return "Queued";
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
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${apiUrl}/api/jobs`);
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

  // Poll database if any jobs are active
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
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${apiUrl}/api/job/${jobId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Could not delete project. Please try again.");
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
          <p className="subtitle">Salvaged core clipping engine workspace.</p>
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
          <p>Analyzing local database...</p>
        </div>
      ) : jobs.length === 0 ? (
        <div className="empty-state-panel">
          <div className="empty-icon-wrapper">
            <UploadCloud size={40} className="text-cyan-400 pulse-glow" />
          </div>
          <h2>No Projects Found</h2>
          <p>Get started by uploading a video or pasting a URL.</p>
          <div className="empty-actions">
            <Link href="/upload" className="btn btn-primary">
              Upload Video
            </Link>
          </div>
        </div>
      ) : (
        <section className="premium-panel projects-section">
          <div className="projects-toolbar">
            <div className="stats-badges">
              <h2>
                {visibleJobs.length} Project{visibleJobs.length !== 1 ? "s" : ""}
              </h2>
              {activeCount > 0 && <span className="badge badge-active">{activeCount} Processing</span>}
              {readyCount > 0 && <span className="badge badge-ready">{readyCount} Ready</span>}
            </div>
            <div className="search-bar">
              <Search size={16} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search projects..."
              />
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

      <style jsx>{`
        .dashboard-root {
          display: flex;
          flex-direction: column;
          gap: 32px;
        }
        .dashboard-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
        }
        .subtitle {
          color: var(--muted);
          margin-top: 4px;
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
        .loading-card {
          min-height: 250px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 16px;
          color: var(--muted);
        }
        .empty-state-panel {
          border: 1px dashed var(--card-border);
          border-radius: 24px;
          background: rgba(10, 13, 22, 0.4);
          min-height: 350px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 40px;
          text-align: center;
          gap: 16px;
        }
        .empty-icon-wrapper {
          width: 80px;
          height: 80px;
          border-radius: 50%;
          background: rgba(6, 182, 212, 0.1);
          display: grid;
          place-items: center;
        }
        .empty-state-panel h2 {
          font-size: 24px;
        }
        .empty-state-panel p {
          color: var(--muted);
          max-width: 320px;
        }
        .projects-section {
          overflow: hidden;
        }
        .projects-toolbar {
          padding: 24px 32px;
          border-bottom: 1px solid var(--card-border);
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
        }
        .stats-badges {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .badge {
          font-size: 12px;
          font-weight: 700;
          padding: 4px 10px;
          border-radius: 99px;
        }
        .badge-active {
          background: rgba(6, 182, 212, 0.15);
          color: #67e8f9;
        }
        .badge-ready {
          background: rgba(16, 185, 129, 0.15);
          color: #a7f3d0;
        }
        .search-bar {
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid var(--card-border);
          border-radius: 12px;
          padding: 0 16px;
          display: flex;
          align-items: center;
          gap: 10px;
          width: 280px;
          height: 40px;
          color: var(--muted);
        }
        .search-bar input {
          background: transparent;
          border: 0;
          outline: none;
          color: #ffffff;
          font-size: 14px;
          width: 100%;
        }
        .projects-list {
          display: flex;
          flex-direction: column;
        }
      `}</style>
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
  const [logs, setLogs] = useState<string[]>([job.message || "Checking video status..."]);
  const [showLogs, setShowLogs] = useState(true);
  const logEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Sync props updates
  useEffect(() => {
    setLocalJob(job);
    if (job.message) {
      setLogs((prev) => {
        if (prev[prev.length - 1] === job.message) return prev;
        return [...prev, job.message!];
      });
    }
  }, [job]);

  // Connect WebSocket for active pipeline states
  useEffect(() => {
    if (!ACTIVE_STATUSES.includes(localJob.status)) return;
    if (wsRef.current) return;

    let isMounted = true;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const wsProtocol = apiUrl.startsWith("https") ? "wss" : "ws";
    const wsUrl = `${apiUrl.replace(/^http/, wsProtocol)}/ws/${localJob.id}`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      if (!isMounted) return;
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'progress') {
          setLocalJob((prev) => ({
            ...prev,
            progress: data.progress,
            message: data.message,
            stage: data.stage,
            status: 'processing'
          }));
          if (data.message) {
            setLogs((prev) => {
              if (prev[prev.length - 1] === data.message) return prev;
              return [...prev, data.message];
            });
          }
        } else if (data.type === 'complete') {
          setLocalJob((prev) => ({
            ...prev,
            status: 'complete',
            progress: 100,
            message: data.message,
            clips: data.clips || []
          }));
          setLogs((prev) => [...prev, data.message]);
          onJobCompleted();
        } else if (data.type === 'error') {
          setLocalJob((prev) => ({
            ...prev,
            status: 'error',
            progress: 0,
            message: data.message
          }));
          setLogs((prev) => [...prev, `[CRITICAL PIPELINE ERROR] ${data.message}`]);
          onJobCompleted();
        }
      } catch (e) {
        console.error("Failed to parse socket packet:", e);
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected for job", localJob.id);
    };

    return () => {
      isMounted = false;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [localJob.id, localJob.status, onJobCompleted]);

  // Autoscroll logs
  useEffect(() => {
    if (isExpanded && showLogs && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, isExpanded, showLogs]);

  const progress = Math.max(0, Math.min(100, localJob.progress || (localJob.status === "complete" ? 100 : 0)));

  // Pipeline step visual calculator
  const steps = useMemo(() => {
    const defaultSteps = [
      { id: 1, name: "Media Import", desc: "Checking source..." },
      { id: 2, name: "Audio Transcription", desc: "Whisper audio mapping..." },
      { id: 3, name: "Viral Moments Analysis", desc: "LLM virality scoring..." },
      { id: 4, name: "Cut Alignment", desc: "Pause boundary snapping..." },
      { id: 5, name: "Compilation & Rendering", desc: "Dynamic crops & subtitles..." },
    ];

    const status = localJob.status;
    const stage = localJob.stage || 'queued';
    let activeIdx = -1;

    if (status === 'complete') {
      activeIdx = 5;
    } else if (status === 'error') {
      if (stage === 'downloading') activeIdx = 0;
      else if (stage === 'queued' || stage === 'preflighted' || stage === 'transcribed') activeIdx = 1;
      else if (stage === 'analyzed') activeIdx = 2;
      else if (stage === 'aligned') activeIdx = 3;
      else if (stage === 'clips_rendering') activeIdx = 4;
      else activeIdx = 0;
    } else {
      if (stage === 'downloading') activeIdx = 0;
      else if (stage === 'queued' || stage === 'preflighted') activeIdx = 1;
      else if (stage === 'transcribed') activeIdx = 2;
      else if (stage === 'analyzed') activeIdx = 3;
      else if (stage === 'aligned') activeIdx = 4;
      else if (stage === 'clips_rendering') activeIdx = 4;
      else activeIdx = 0;
    }

    return defaultSteps.map((step, idx) => {
      let stepStatus: 'todo' | 'active' | 'done' | 'error' = 'todo';
      if (status === 'error' && idx === activeIdx) {
        stepStatus = 'error';
      } else if (idx < activeIdx) {
        stepStatus = 'done';
      } else if (idx === activeIdx) {
        stepStatus = 'active';
      }
      return { ...step, status: stepStatus };
    });
  }, [localJob.status, localJob.stage]);

  const expandable = ACTIVE_STATUSES.includes(localJob.status) || localJob.status === "error";

  return (
    <div className={`project-row-wrapper ${localJob.status}`}>
      <div className="project-row" onClick={() => expandable && setIsExpanded(!isExpanded)}>
        <div className="col-info">
          <div className="status-avatar">
            <StatusIcon status={localJob.status} />
          </div>
          <div className="info-text">
            <h3>{projectName(localJob)}</h3>
            <span className="job-id">{localJob.id}</span>
          </div>
        </div>

        <div className="col-stats">
          <span className={`status-pill pill-${localJob.status}`}>
            {statusLabel(localJob.status)}
          </span>
          <span className="clips-count">
            {localJob.clips?.length || 0} Clip{(localJob.clips?.length || 0) !== 1 ? "s" : ""}
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
          {expandable && (
            <button className="toggle-btn" type="button">
              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          )}
          <button
            className="delete-btn"
            onClick={(e) => onDelete(localJob.id, e)}
            disabled={deletingJobId === localJob.id}
          >
            {deletingJobId === localJob.id ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
          </button>
        </div>
      </div>

      {isExpanded && expandable && (
        <div className="expansion-panel">
          <div className="panel-layout">
            {/* Checklist */}
            <div className="checklist-col">
              <h4 className="panel-title">Pipeline Progress</h4>
              <div className="steps-container">
                {steps.map((step, idx) => (
                  <div key={step.id} className={`step-row ${step.status}`}>
                    <div className="step-bullet">
                      <div className={`bullet-circle ${step.status}`}>
                        {step.status === 'done' && "✓"}
                        {step.status === 'active' && <span className="active-dot" />}
                        {step.status === 'error' && "!"}
                        {step.status === 'todo' && "•"}
                      </div>
                      {idx < steps.length - 1 && (
                        <div className={`bullet-line ${step.status === 'done' ? 'done' : ''}`} />
                      )}
                    </div>
                    <div className="step-details">
                      <span className="step-name">{step.name}</span>
                      <span className="step-desc">{step.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Console Log */}
            {showLogs && (
              <div className="console-col">
                <div className="console-header">
                  <h4 className="panel-title flex-items">
                    <Terminal size={14} className="text-primary mr-2" />
                    Console Output
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

      <style jsx>{`
        .project-row-wrapper {
          border-top: 1px solid var(--card-border);
          transition: background 0.2s ease;
        }
        .project-row-wrapper:hover {
          background: rgba(255, 255, 255, 0.01);
        }
        .project-row {
          display: grid;
          grid-template-columns: 2fr 1.5fr 1fr;
          align-items: center;
          padding: 24px 32px;
          gap: 24px;
          cursor: pointer;
        }
        .col-info {
          display: flex;
          align-items: center;
          gap: 16px;
          min-width: 0;
        }
        .status-avatar {
          width: 44px;
          height: 44px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid var(--card-border);
          border-radius: 12px;
          display: grid;
          place-items: center;
          flex-shrink: 0;
        }
        .info-text {
          min-width: 0;
        }
        .info-text h3 {
          font-size: 15px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .job-id {
          font-size: 12px;
          color: var(--muted-dark);
          font-family: monospace;
        }
        .col-stats {
          display: flex;
          align-items: center;
          gap: 16px;
        }
        .status-pill {
          font-size: 11px;
          font-weight: 800;
          text-transform: uppercase;
          padding: 3px 8px;
          border-radius: 99px;
          letter-spacing: 0.05em;
          white-space: nowrap;
        }
        .pill-queued { background: rgba(255,255,255,0.06); color: var(--muted); }
        .pill-downloading { background: rgba(6,182,212,0.1); color: #22d3ee; }
        .pill-processing { background: rgba(168,85,247,0.1); color: #c084fc; }
        .pill-complete { background: rgba(16,185,129,0.1); color: #34d399; }
        .pill-error { background: rgba(244,63,94,0.1); color: #fb7185; }

        .clips-count {
          font-size: 13px;
          color: var(--muted);
          font-weight: 600;
          white-space: nowrap;
        }
        .progress-track {
          flex: 1;
          height: 6px;
          background: rgba(255, 255, 255, 0.06);
          border-radius: 99px;
          overflow: hidden;
          min-width: 80px;
        }
        .progress-fill {
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, var(--primary), var(--secondary));
          transition: width 0.4s ease;
        }
        .col-actions {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 12px;
        }
        .btn-sm {
          padding: 8px 16px;
          border-radius: 10px;
          font-size: 12px;
          height: 36px;
        }
        .toggle-btn, .delete-btn {
          width: 36px;
          height: 36px;
          border-radius: 10px;
          border: 0;
          background: rgba(255,255,255,0.04);
          color: var(--muted);
          display: grid;
          place-items: center;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .toggle-btn:hover {
          background: rgba(255, 255, 255, 0.08);
          color: #ffffff;
        }
        .delete-btn:hover {
          background: rgba(244,63,94,0.1);
          color: #fb7185;
        }
        .expansion-panel {
          background: rgba(0, 0, 0, 0.25);
          border-top: 1px solid var(--card-border);
          padding: 24px 32px 32px;
        }
        .panel-layout {
          display: grid;
          grid-template-columns: 1fr 1.2fr;
          gap: 40px;
        }
        .panel-title {
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: #ffffff;
          margin-bottom: 20px;
        }
        .flex-items {
          display: flex;
          align-items: center;
        }
        .mr-2 { margin-right: 8px; }
        .text-primary { color: var(--primary); }
        
        /* Steps Timeline */
        .steps-container {
          display: flex;
          flex-direction: column;
        }
        .step-row {
          display: flex;
          gap: 16px;
        }
        .step-bullet {
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        .bullet-circle {
          width: 22px;
          height: 22px;
          border-radius: 50%;
          background: rgba(255,255,255,0.04);
          border: 1px solid var(--card-border);
          display: grid;
          place-items: center;
          font-size: 10px;
          font-weight: 800;
          color: var(--muted-dark);
          transition: all 0.3s ease;
        }
        .bullet-circle.done {
          background: rgba(16,185,129,0.15);
          border-color: #10b981;
          color: #10b981;
        }
        .bullet-circle.active {
          background: rgba(246,92,139,0.15);
          border-color: var(--primary);
          color: var(--primary);
          box-shadow: 0 0 10px var(--primary-glow);
        }
        .bullet-circle.error {
          background: rgba(244,63,94,0.15);
          border-color: #ef4444;
          color: #ef4444;
        }
        .active-dot {
          width: 6px;
          height: 6px;
          background: var(--primary);
          border-radius: 50%;
          animation: spin 1.5s infinite linear;
        }
        .bullet-line {
          width: 2px;
          flex-grow: 1;
          min-height: 24px;
          background: rgba(255,255,255,0.08);
          margin: 4px 0;
        }
        .bullet-line.done {
          background: #10b981;
        }
        .step-details {
          display: flex;
          flex-direction: column;
          padding-bottom: 20px;
        }
        .step-name {
          font-size: 13px;
          font-weight: 700;
          color: rgba(255,255,255,0.5);
        }
        .step-desc {
          font-size: 11px;
          color: var(--muted-dark);
        }
        .step-row.active .step-name {
          color: #ffffff;
        }
        .step-row.done .step-name {
          color: rgba(255,255,255,0.8);
        }
        .step-row.error .step-name {
          color: #fb7185;
        }

        /* Console styling */
        .console-col {
          display: flex;
          flex-direction: column;
        }
        .console-terminal {
          background: #020306;
          border: 1px solid var(--card-border);
          border-radius: 14px;
          padding: 16px;
          font-family: monospace;
          font-size: 11px;
          color: #a78bfa;
          line-height: 1.6;
          min-height: 180px;
          max-height: 240px;
          overflow-y: auto;
          box-shadow: inset 0 2px 10px rgba(0,0,0,0.8);
        }
        .log-line {
          margin-bottom: 4px;
          word-break: break-all;
          white-space: pre-wrap;
        }
        .log-arrow {
          color: var(--primary);
          font-weight: bold;
          margin-right: 6px;
        }

        @media (max-width: 860px) {
          .project-row {
            grid-template-columns: 1fr;
            padding: 20px;
          }
          .panel-layout {
            grid-template-columns: 1fr;
            gap: 24px;
          }
        }
      `}</style>
    </div>
  );
}
