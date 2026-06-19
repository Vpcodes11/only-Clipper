"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { UploadCloud, Link as LinkIcon, Loader2, PlayCircle, Sliders, Cpu } from "lucide-react";

export default function NewProject() {
  const router = useRouter();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  
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
        const res = await fetch(`/api/presets`);
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
              reject(new Error(`Server returned ${xhr.status}: ${xhr.responseText || xhr.statusText}`));
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

    </div>
  );
}
