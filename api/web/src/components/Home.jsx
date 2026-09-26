import { useEffect, useRef, useState } from "react";
import { ArrowUpFromLine, ChevronRight, Mic } from "lucide-react";
import { api } from "../api.js";
import { useT } from "../i18n.js";
import { formatDate, isoDate } from "../util.js";
import Recorder from "./Recorder.jsx";

const MEDIA_EXT = /\.(mp3|wav|m4a|aac|ogg|oga|opus|webm|flac|wma|amr|mp4|mov|mkv|3gp)$/i;
const isMedia = (f) => /^(audio|video)\//.test(f.type) || MEDIA_EXT.test(f.name);

export default function Home({ onStarted, defaultType, lang }) {
  const t = useT();
  const [mode, setMode] = useState("idle");        // idle | recording | uploading
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);

  async function start(blob, filename, date) {
    setError(null);
    setMode("uploading");
    setProgress(0);
    try {
      const job = await api.create(blob, filename, defaultType, date, setProgress);
      onStarted(job.id);
    } catch {
      setError(t.uploadFailed);
      setMode("idle");
    }
  }

  function takeFile(file) {
    if (!file) return;
    if (!isMedia(file)) { setError(t.notAudio); return; }
    // A file's modified date is usually the day it was recorded.
    start(file, file.name, isoDate(new Date(file.lastModified || Date.now())));
  }

  return (
    <section className="home">
      <h1 className="display">{t.homeTitle}</h1>
      <p className="lede">{t.homeLede}</p>

      {mode === "recording" && (
        <Recorder
          onDone={(blob, ext) => start(blob, `inregistrare-${isoDate()}.${ext}`, isoDate())}
          onCancel={() => setMode("idle")}
          onError={(msg) => { setError(msg); setMode("idle"); }}
        />
      )}

      {mode === "uploading" && (
        <div className="panel upload-panel" role="status" aria-live="polite">
          <p className="panel-title">{t.uploading}</p>
          <div className="bar"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
          <p className="muted small">{Math.round(progress * 100)}%</p>
        </div>
      )}

      {mode === "idle" && (
        <>
          <DropZone onFile={takeFile} />
          <div className="or"><span>{t.or}</span></div>
          <button className="record-cta" onClick={() => { setError(null); setMode("recording"); }}>
            <span className="record-cta-icon"><Mic size={20} strokeWidth={2} /></span>
            {t.recordNow}
          </button>
        </>
      )}

      {error && <p className="notice warn" role="alert">{error}</p>}

      {mode === "idle" && <Recent onOpen={onStarted} lang={lang} />}
    </section>
  );
}

function DropZone({ onFile }) {
  const t = useT();
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const touch = matchMedia("(pointer: coarse)").matches;   // phones/tablets can't drag files

  // Accept a drop anywhere on the page, and never let the browser open the file itself.
  useEffect(() => {
    let depth = 0;
    const enter = (e) => { e.preventDefault(); depth++; setOver(true); };
    const leave = (e) => { e.preventDefault(); if (--depth <= 0) { depth = 0; setOver(false); } };
    const overFn = (e) => e.preventDefault();
    const drop = (e) => { e.preventDefault(); depth = 0; setOver(false); onFile(e.dataTransfer.files[0]); };
    addEventListener("dragenter", enter);
    addEventListener("dragleave", leave);
    addEventListener("dragover", overFn);
    addEventListener("drop", drop);
    return () => {
      removeEventListener("dragenter", enter);
      removeEventListener("dragleave", leave);
      removeEventListener("dragover", overFn);
      removeEventListener("drop", drop);
    };
  }, [onFile]);

  return (
    <button type="button" className={`dropzone${over ? " over" : ""}`} onClick={() => input.current.click()}>
      <span className="dropzone-icon"><ArrowUpFromLine size={26} strokeWidth={1.75} /></span>
      <span className="dropzone-title">{over ? t.dropActive : touch ? t.dropTitleTouch : t.dropTitle}</span>
      <span className="dropzone-hint">{touch ? t.dropHintTouch : t.dropHint}</span>
      <span className="dropzone-formats">{t.dropFormats}</span>
      <input ref={input} type="file" accept="audio/*,video/*" hidden
             onChange={(e) => { onFile(e.target.files[0]); e.target.value = ""; }} />
    </button>
  );
}

function Recent({ onOpen, lang }) {
  const t = useT();
  const [jobs, setJobs] = useState([]);
  useEffect(() => { api.recent().then(setJobs).catch(() => {}); }, []);
  if (!jobs.length) return null;

  const kind = (stage) => (["review", "done", "failed"].includes(stage) ? stage : "working");
  return (
    <div className="recent">
      <h2 className="eyebrow">{t.recent}</h2>
      <ul>
        {jobs.slice(0, 5).map((j) => (
          <li key={j.id}>
            <button onClick={() => onOpen(j.id)}>
              <span className="recent-title">{j.title || t.untitled}</span>
              <span className="recent-date">{formatDate(j.meeting_date, lang)}</span>
              <span className={`chip ${kind(j.stage)}`}>{t.status[kind(j.stage)]}</span>
              <ChevronRight size={16} className="muted" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
