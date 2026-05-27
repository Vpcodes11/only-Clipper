"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, Link as LinkIcon, Loader2, PlayCircle, Sliders, Cpu } from "lucide-react";

export default function NewProject() {
  const router = useRouter();
  
  // Form fields state
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preset, setPreset] = useState("tiktok");
  const [captionStyle, setCaptionStyle] = useState("typography_motion");
  const [provider, setProvider] = useState("groq");
  
  // UI and options state
  const [isDragging, setIsDragging] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [availablePresets, setAvailablePresets] = useState<any>({});
  const [availableStyles, setAvailableStyles] = useState<any>({});

  // Fetch presets and styles from backend
  useEffect(() => {
    const fetchOptions = async () => {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const res = await fetch(`${apiUrl}/api/presets`);
        if (res.ok) {
          const data = await res.json();
          setAvailablePresets(data.presets || {});
          setAvailableStyles(data.caption_styles || {});
        }
      } catch (e) {
        console.error("Failed to load presets:", e);
      }
    };
    fetchOptions();
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    setErrorMsg(null);
    setUrl("");

    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles && droppedFiles.length > 0) {
      const selectedFile = droppedFiles[0];
      if (selectedFile.type.startsWith("video/")) {
        setFile(selectedFile);
      } else {
        setErrorMsg("Invalid file type. Only video files (MP4, MOV, WEBM) are supported.");
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setErrorMsg(null);
    setUrl("");
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const handleUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setErrorMsg(null);
    setFile(null);
    setUrl(e.target.value);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file && !url.trim()) {
      setErrorMsg("Please upload a local video file or paste a public video URL.");
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);
    setUploadProgress(0);

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const formData = new FormData();
      formData.append("preset", preset);
      formData.append("caption_style", captionStyle);
      formData.append("provider", provider);

      if (url.trim()) {
        formData.append("url", url.trim());
      } else if (file) {
        formData.append("file", file);
      }

      // XHR for progress tracking
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${apiUrl}/api/upload`);

      // Track progress for local uploads
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = Math.round((event.loaded / event.total) * 100);
          setUploadProgress(percent);
        }
      };

      const requestPromise = new Promise((resolve, reject) => {
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText));
          } else {
            try {
              const err = JSON.parse(xhr.responseText);
              reject(new Error(err.detail || "Upload failed. Check file bounds or URL protocol."));
            } catch {
              reject(new Error("Server returned an error status."));
            }
          }
        };
        xhr.onerror = () => reject(new Error("Network connection error."));
      });

      xhr.send(formData);
      await requestPromise;

      // Success, route to dashboard
      router.push("/dashboard");
    } catch (err: any) {
      console.error("Failed to submit job:", err);
      setErrorMsg(err.message || "An unexpected error occurred during submission.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="upload-root animate-fade">
      <header className="upload-header">
        <h1>Create Video Job</h1>
        <p className="subtitle">Upload high-res source videos or import from YouTube.</p>
      </header>

      {errorMsg && (
        <div className="error-banner">
          <span>{errorMsg}</span>
        </div>
      )}

      <form className="upload-form" onSubmit={handleSubmit}>
        <div className="form-main">
          {/* File upload/URL card */}
          <div className="premium-panel source-card">
            <div
              className={`dropzone ${isDragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input
                id="file-upload"
                type="file"
                accept="video/*"
                onChange={handleFileChange}
                style={{ display: "none" }}
              />
              
              {file ? (
                <div className="file-preview">
                  <PlayCircle size={48} className="text-primary pulse-glow" />
                  <h3>{file.name}</h3>
                  <p>{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setFile(null)}
                  >
                    Remove File
                  </button>
                </div>
              ) : (
                <label htmlFor="file-upload" className="dropzone-label">
                  <UploadCloud size={48} className="text-muted-dark hover-accent" />
                  <h3>Drag & drop video file</h3>
                  <p className="small">MP4, MOV, WEBM — up to 2 GB</p>
                  <span className="btn btn-secondary btn-sm select-btn">Browse Files</span>
                </label>
              )}
            </div>

            <div className="divider">
              <span>OR</span>
            </div>

            <div className="url-input-wrapper">
              <label className="input-label">
                <LinkIcon size={16} />
                <span>Paste video URL</span>
              </label>
              <input
                type="url"
                value={url}
                onChange={handleUrlChange}
                placeholder="https://www.youtube.com/watch?v=..."
                className="form-input"
              />
              <p className="input-hint">Compatible with YouTube, Vimeo, Twitch and public MP4 links.</p>
            </div>
          </div>

          {/* Preset settings sidebar */}
          <div className="premium-panel settings-card">
            <h2>
              <Sliders size={18} className="mr-2 text-secondary" />
              Clipping Presets
            </h2>

            <div className="setting-group">
              <label>Export Layout Preset</label>
              <select value={preset} onChange={(e) => setPreset(e.target.value)} className="form-input">
                {Object.entries(availablePresets).map(([key, value]: any) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
                {Object.keys(availablePresets).length === 0 && (
                  <>
                    <option value="tiktok">TikTok / Reels (9:16)</option>
                    <option value="youtube_shorts">YouTube Shorts (9:16)</option>
                    <option value="square">Square (1:1)</option>
                    <option value="landscape">Landscape (16:9)</option>
                  </>
                )}
              </select>
            </div>

            <div className="setting-group">
              <label>Karaoke Caption Style</label>
              <select
                value={captionStyle}
                onChange={(e) => setCaptionStyle(e.target.value)}
                className="form-input"
              >
                {Object.entries(availableStyles).map(([key, value]: any) => (
                  <option key={key} value={key}>
                    {value.name}
                  </option>
                ))}
                {Object.keys(availableStyles).length === 0 && (
                  <>
                    <option value="typography_motion">Typography Motion</option>
                    <option value="hormozi">Hormozi Caps</option>
                    <option value="ali_abdaal">Ali Abdaal Minimal</option>
                    <option value="beast_mode">Beast Mode Giant</option>
                    <option value="stealth_pro">Stealth Pro Purple</option>
                    <option value="viral">Viral Golden Gold</option>
                  </>
                )}
              </select>
            </div>

            <div className="setting-group">
              <label>
                <Cpu size={14} className="mr-1 inline text-muted" />
                AI Processing Pipeline
              </label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="form-input"
              >
                <option value="groq">Groq (LLaMA-3.1 + Whisper Turbo)</option>
                <option value="openai">OpenAI (GPT-4o-mini + Whisper-1)</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="btn btn-accent btn-large submit-btn"
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={18} className="spin mr-2" />
                  {file ? `Uploading (${uploadProgress}%)` : "Initializing Pipeline..."}
                </>
              ) : (
                "Launch Clipping Pipeline"
              )}
            </button>
          </div>
        </div>
      </form>

      <style jsx>{`
        .upload-root {
          display: flex;
          flex-direction: column;
          gap: 32px;
          animation: fade 0.3s ease;
        }
        .upload-header {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .subtitle {
          color: var(--muted);
        }
        .error-banner {
          background: rgba(244, 63, 94, 0.1);
          border: 1px solid rgba(244, 63, 94, 0.2);
          border-radius: 12px;
          padding: 16px;
          color: #fda4af;
          font-size: 14px;
        }
        .upload-form {
          width: 100%;
        }
        .form-main {
          display: grid;
          grid-template-columns: 1.8fr 1fr;
          gap: 32px;
          align-items: start;
        }
        .source-card {
          padding: 40px;
          display: flex;
          flex-direction: column;
          gap: 32px;
        }
        .dropzone {
          border: 2px dashed var(--card-border);
          border-radius: 20px;
          background: rgba(255, 255, 255, 0.01);
          transition: all 0.2s ease;
          min-height: 250px;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .dropzone.dragging {
          border-color: var(--secondary);
          background: rgba(6, 182, 212, 0.05);
        }
        .dropzone.has-file {
          border-style: solid;
          background: rgba(255, 255, 255, 0.02);
        }
        .dropzone-label {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          cursor: pointer;
          width: 100%;
          padding: 40px;
          text-align: center;
        }
        .dropzone-label h3 {
          font-size: 16px;
        }
        .dropzone-label p {
          color: var(--muted);
          font-size: 13px;
        }
        .file-preview {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 40px;
          text-align: center;
        }
        .file-preview h3 {
          font-size: 16px;
          word-break: break-all;
          max-width: 400px;
        }
        .file-preview p {
          color: var(--muted);
          font-size: 13px;
        }
        .btn-sm {
          padding: 6px 12px;
          border-radius: 8px;
          font-size: 12px;
        }
        .divider {
          display: flex;
          align-items: center;
          text-align: center;
          color: var(--muted-dark);
          font-size: 12px;
          font-weight: 700;
        }
        .divider::before,
        .divider::after {
          content: "";
          flex: 1;
          border-bottom: 1px solid var(--card-border);
        }
        .divider::before {
          margin-right: 16px;
        }
        .divider::after {
          margin-left: 16px;
        }
        .url-input-wrapper {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .input-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          font-weight: 650;
          color: rgba(255,255,255,0.8);
        }
        .input-hint {
          color: var(--muted-dark);
          font-size: 11px;
        }
        
        .settings-card {
          padding: 32px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }
        .settings-card h2 {
          font-size: 18px;
          display: flex;
          align-items: center;
        }
        .mr-2 { margin-right: 8px; }
        .mr-1 { margin-right: 4px; }
        .text-secondary { color: var(--secondary); }
        .setting-group {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .setting-group label {
          font-size: 13px;
          font-weight: 600;
          color: var(--muted);
        }
        .submit-btn {
          width: 100%;
          min-height: 48px;
          font-size: 15px;
          margin-top: 12px;
        }
        
        @keyframes fade {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        
        @media (max-width: 860px) {
          .form-main {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}
