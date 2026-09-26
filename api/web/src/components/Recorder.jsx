import { useEffect, useRef, useState } from "react";
import { Pause, Play, Square, X } from "lucide-react";
import { useT } from "../i18n.js";
import { clock } from "../util.js";

const BARS = 40;

export default function Recorder({ onDone, onCancel, onError }) {
  const t = useT();
  const [ready, setReady] = useState(false);
  const [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState(() => Array(BARS).fill(0));
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const rec = useRef(null);
  const clockRef = useRef({ total: 0, since: 0 });   // ms recorded before the current run

  useEffect(() => {
    let cancelled = false, stream, ctx, raf, timer, wakeLock;
    const chunks = [];

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false } });
      } catch {
        if (!cancelled) onError(t.micDenied);
        return;
      }
      if (cancelled) { stream.getTracks().forEach((tr) => tr.stop()); return; }

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = () => {
        if (recorder.discarded) return;
        const type = recorder.mimeType || "audio/webm";
        onDone(new Blob(chunks, { type }), type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm");
      };
      recorder.start(1000);
      rec.current = recorder;
      clockRef.current = { total: 0, since: Date.now() };
      setReady(true);

      // Live level meter: RMS of the mic signal, scrolling right to left.
      ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      let last = 0;
      const draw = (now) => {
        raf = requestAnimationFrame(draw);
        if (now - last < 70) return;
        last = now;
        analyser.getFloatTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((s, v) => s + v * v, 0) / buf.length);
        const level = recorder.state === "recording" ? Math.min(1, rms * 6) : 0;
        setLevels((prev) => [...prev.slice(1), level]);
      };
      raf = requestAnimationFrame(draw);

      timer = setInterval(() => {
        const c = clockRef.current;
        setElapsed((c.total + (recorder.state === "recording" ? Date.now() - c.since : 0)) / 1000);
      }, 250);

      try { wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not supported */ }
    })();

    const guard = (e) => { e.preventDefault(); e.returnValue = ""; };
    addEventListener("beforeunload", guard);

    return () => {
      cancelled = true;
      removeEventListener("beforeunload", guard);
      cancelAnimationFrame(raf);
      clearInterval(timer);
      if (rec.current?.state !== "inactive" && rec.current) { rec.current.discarded = true; rec.current.stop(); }
      stream?.getTracks().forEach((tr) => tr.stop());
      ctx?.close();
      wakeLock?.release?.();
    };
    // Runs once per mount; callbacks are read at event time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function togglePause() {
    const r = rec.current, c = clockRef.current;
    if (!r) return;
    if (r.state === "recording") { r.pause(); c.total += Date.now() - c.since; setPaused(true); }
    else { r.resume(); c.since = Date.now(); setPaused(false); }
  }

  function finish() {
    const r = rec.current;
    if (!r) return;
    rec.current = null;   // so unmount cleanup doesn't discard it
    r.stop();
    r.stream.getTracks().forEach((tr) => tr.stop());
  }

  function discard() {
    if (!confirmDiscard) { setConfirmDiscard(true); setTimeout(() => setConfirmDiscard(false), 3000); return; }
    onCancel();
  }

  return (
    <div className={`panel recorder${paused ? " paused" : ""}`} role="region" aria-label={t.recording}>
      <div className="rec-status">
        <span className="rec-dot" aria-hidden="true" />
        {paused ? t.paused : t.recording}
      </div>
      <div className="rec-time" aria-live="off">{clock(elapsed)}</div>
      <div className="meter" aria-hidden="true">
        {levels.map((v, i) => <i key={i} style={{ transform: `scaleY(${0.08 + v * 0.92})` }} />)}
      </div>
      <p className="muted small">{t.recordingTip}</p>
      <div className="rec-actions">
        <button className="btn ghost" onClick={discard} disabled={!ready}>
          <X size={16} /> {confirmDiscard ? t.discardConfirm : t.discard}
        </button>
        <button className="btn secondary" onClick={togglePause} disabled={!ready}>
          {paused ? <><Play size={16} /> {t.resume}</> : <><Pause size={16} /> {t.pause}</>}
        </button>
        <button className="btn primary" onClick={finish} disabled={!ready || elapsed < 1}>
          <Square size={14} fill="currentColor" /> {t.finish}
        </button>
      </div>
    </div>
  );
}
