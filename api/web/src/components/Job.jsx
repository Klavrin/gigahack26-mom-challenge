import { useEffect, useState } from "react";
import { Check, CircleAlert, ExternalLink, Plus } from "lucide-react";
import { api } from "../api.js";
import { useT } from "../i18n.js";
import { clock } from "../util.js";
import Review from "./Review.jsx";

const WAITING = ["review", "done", "failed"];

export default function Job({ id, onNew, lang }) {
  const [job, setJob] = useState(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let alive = true, timer;
    const tick = async () => {
      try {
        const j = await api.job(id);
        if (!alive) return;
        setJob(j);
        if (!WAITING.includes(j.stage)) timer = setTimeout(tick, 1000);
      } catch {
        if (alive) setMissing(true);
      }
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  if (missing) return <Failed onNew={onNew} notFound />;
  if (!job) return <div className="spinner" aria-hidden="true" />;
  if (job.stage === "failed") return <Failed onNew={onNew} error={job.error} />;
  if (job.stage === "done") return <Sent job={job} onNew={onNew} />;
  if (job.stage === "review" || job.stage === "sending") return <Review job={job} onSent={setJob} lang={lang} />;
  return <Processing job={job} />;
}

function Processing({ job }) {
  const t = useT();
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const i = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(i); }, []);

  const current = ["queued", "transcribing", "correcting"].includes(job.stage) ? 0 : 1;
  const steps = [
    { title: t.stepListen, detail: t.stepListenDetail },
    { title: t.stepWrite, detail: t.stepWriteDetail },
    { title: t.stepReview },
  ];

  return (
    <section className="processing" aria-live="polite">
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={i} className={i < current ? "done" : i === current ? "active" : ""}>
            <span className="step-mark" aria-hidden="true">{i < current ? <Check size={14} strokeWidth={3} /> : i + 1}</span>
            <div className="step-body">
              <p className="step-title">{s.title}</p>
              {s.detail && <p className="step-detail">{s.detail}</p>}
              {i === 0 && current === 0 && job.stage !== "queued" && (
                <div className="bar"><div style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} /></div>
              )}
              {i === 1 && current === 1 && <div className="bar indeterminate"><div /></div>}
            </div>
          </li>
        ))}
      </ol>
      {job.stage === "queued" && <p className="notice">{t.queued}</p>}
      <p className="muted small center">
        {t.elapsed} {clock(now / 1000 - job.created)} · {t.canLeave}
      </p>
    </section>
  );
}

function Sent({ job, onNew }) {
  const t = useT();
  const tm = job.timings || {};
  const processing = (tm.total_s || 0) + (tm.send_s || 0);
  return (
    <section className="sent">
      <div className="sent-check" aria-hidden="true"><Check size={30} strokeWidth={2.5} /></div>
      <h1 className="display small-display">{t.sentTitle}</h1>
      <p className="lede">{t.sentTo(t.types[job.meeting_type] || job.meeting_type)}</p>
      {job.audio_s > 0 && (
        <dl className="stats">
          <div><dt>{t.statAudio}</dt><dd>{clock(job.audio_s)}</dd></div>
          <div><dt>{t.statProcessing}</dt><dd>{clock(processing)}</dd></div>
        </dl>
      )}
      <div className="sent-actions">
        <button className="btn primary" onClick={onNew}><Plus size={16} /> {t.newMeeting}</button>
        <a className="btn ghost" href={`/api/jobs/${job.id}/mom.html`} target="_blank" rel="noreferrer">
          {t.viewEmail} <ExternalLink size={14} />
        </a>
      </div>
    </section>
  );
}

function Failed({ error, onNew, notFound }) {
  const t = useT();
  return (
    <section className="sent failed">
      <div className="sent-check" aria-hidden="true"><CircleAlert size={30} strokeWidth={2} /></div>
      <h1 className="display small-display">{t.failedTitle}</h1>
      <p className="lede">{notFound ? t.notFound : t.failedText}</p>
      {error && (
        <details className="tech">
          <summary>{t.details}</summary>
          <code>{error}</code>
        </details>
      )}
      <div className="sent-actions">
        <button className="btn primary" onClick={onNew}>{t.tryAgain}</button>
      </div>
    </section>
  );
}
