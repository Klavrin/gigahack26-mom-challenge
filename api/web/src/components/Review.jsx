import { useEffect, useMemo, useState } from "react";
import { CircleAlert, CircleCheck, FileText, Quote, Send } from "lucide-react";
import { api } from "../api.js";
import { useT } from "../i18n.js";
import { MEETING_TYPES, clock, findSegment, formatDate, initials } from "../util.js";
import Transcript from "./Transcript.jsx";

export default function Review({ job, onSent, lang }) {
  const t = useT();
  const [mom, setMom] = useState(null);
  const [segments, setSegments] = useState([]);
  const [items, setItems] = useState([]);
  const [type, setType] = useState(job.meeting_type);
  const [sending, setSending] = useState(job.stage === "sending");
  const [error, setError] = useState(null);
  const [transcriptAt, setTranscriptAt] = useState(null);   // null = closed, -1 = open at top
  const [approver, setApprover] = useState(loadApprover);    // who signs off; remembered per browser

  useEffect(() => {
    Promise.all([api.mom(job.id), api.segments(job.id)]).then(([m, s]) => {
      setMom(m);
      setSegments(s);
      setItems((m.action_items || []).map((a) => ({ owner: a.owner || "", deadline: a.deadline || "" })));
    });
  }, [job.id]);

  const missing = items.reduce((n, a) => n + !a.owner.trim() + !a.deadline, 0);
  const people = useMemo(() => mom?.participants || [], [mom]);

  if (!mom) return <div className="spinner" aria-hidden="true" />;

  const update = (i, field, value) =>
    setItems((prev) => prev.map((a, j) => (j === i ? { ...a, [field]: value } : a)));

  function jumpToMissing() {
    const el = document.querySelector(".task .field.empty input");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.focus({ preventScroll: true });
  }

  async function send() {
    const name = approver.trim();
    if (!name) {
      document.getElementById("approver")?.focus();
      return;
    }
    setSending(true);
    setError(null);
    saveApprover(name);
    try {
      onSent(await api.send(job.id, { meeting_type: type, action_items: items, approved_by: name }));
    } catch (e) {
      setError(`${t.sendFailed} ${e.message}`);
      setSending(false);
    }
  }

  const evidence = (quote) => (
    <Evidence quote={quote} segments={segments} onOpen={(i) => setTranscriptAt(i)} />
  );

  return (
    <div className="review">
      <article className="doc">
        <p className="eyebrow">{t.draft} · {formatDate(job.meeting_date, lang)}</p>
        <h1 className="doc-title">{mom.title}</h1>
        <p className="doc-summary">{mom.summary}</p>

        {people.length > 0 && (
          <ul className="people" aria-label={t.participants}>
            {people.map((p) => (
              <li key={p}><span className="avatar" aria-hidden="true">{initials(p)}</span>{p}</li>
            ))}
          </ul>
        )}

        <section className="doc-section">
          <h2>{t.decisions}</h2>
          {mom.decisions?.length ? (
            <ol className="decisions">
              {mom.decisions.map((d, i) => (
                <li key={i}><p>{d.decision}</p>{evidence(d.evidence)}</li>
              ))}
            </ol>
          ) : <p className="muted">{t.noDecisions}</p>}
        </section>

        <section className="doc-section">
          <h2>{t.tasks}</h2>
          {mom.action_items?.length ? (
            <div className="tasks">
              {mom.action_items.map((a, i) => {
                const v = items[i] || { owner: "", deadline: "" };
                const needs = !v.owner.trim() || !v.deadline;
                return (
                  <div key={i} className={`task${needs ? " needs" : ""}`}>
                    <div className="task-main">
                      <p className="task-text">{a.task}</p>
                      {evidence(a.evidence)}
                    </div>
                    <div className="task-fields">
                      <label className={`field${!v.owner.trim() ? " empty" : ""}`}>
                        <span>{t.owner}</span>
                        <input value={v.owner} list="participants" placeholder={t.ownerMissing}
                               disabled={sending} onChange={(e) => update(i, "owner", e.target.value)} />
                      </label>
                      <label className={`field${!v.deadline ? " empty" : ""}`}>
                        <span>{t.deadline}</span>
                        <input type="date" value={v.deadline} disabled={sending}
                               onChange={(e) => update(i, "deadline", e.target.value)} />
                        {a.deadline_text && <small>{t.spoken} „{a.deadline_text}”</small>}
                      </label>
                    </div>
                  </div>
                );
              })}
              <datalist id="participants">{people.map((p) => <option key={p} value={p} />)}</datalist>
            </div>
          ) : <p className="muted">{t.noTasks}</p>}
        </section>

        {mom.topics?.length > 0 && (
          <section className="doc-section">
            <h2>{t.topics}</h2>
            {mom.topics.map((tp, i) => (
              <p key={i} className="topic"><strong>{tp.topic}.</strong> {tp.discussion}</p>
            ))}
          </section>
        )}

        {mom.open_questions?.length > 0 && (
          <section className="doc-section">
            <h2>{t.openQuestions}</h2>
            <ul className="questions">{mom.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
          </section>
        )}
      </article>

      <aside className="send-panel">
        <div className="panel send-card">
          <h2 className="eyebrow">{t.sendTo}</h2>
          <div className="recipients" role="radiogroup" aria-label={t.sendTo}>
            {MEETING_TYPES.map((k) => (
              <label key={k} className={`recipient${type === k ? " on" : ""}`}>
                <input type="radio" name="recipients" value={k} checked={type === k} aria-label={t.types[k]}
                       disabled={sending} onChange={() => setType(k)} />
                <span className="recipient-name">{t.types[k]}</span>
                <span className="recipient-who">{t.typeWho[k]}</span>
              </label>
            ))}
          </div>

          {missing > 0 ? (
            <button className="attention" onClick={jumpToMissing}>
              <CircleAlert size={16} /> {t.missing(missing)}
            </button>
          ) : items.length > 0 && (
            <p className="all-set"><CircleCheck size={16} /> {t.allSet}</p>
          )}

          <label className={`field${!approver.trim() ? " empty" : ""}`}>
            <span>{t.approvedBy}</span>
            <input id="approver" value={approver} placeholder={t.approverPlaceholder} autoComplete="name"
                   disabled={sending} onChange={(e) => setApprover(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && send()} />
          </label>

          <button className="btn primary block" onClick={send} disabled={sending || !approver.trim()}>
            <Send size={16} /> {sending ? t.sending : t.send}
          </button>
          {error && <p className="notice warn small" role="alert">{error}</p>}
          <p className="muted small center">{t.nothingSent}</p>

          <button className="btn ghost block" onClick={() => setTranscriptAt(-1)}>
            <FileText size={16} /> {t.viewTranscript}
          </button>
        </div>
      </aside>

      {transcriptAt !== null && (
        <Transcript segments={segments} highlight={transcriptAt} onClose={() => setTranscriptAt(null)} />
      )}
    </div>
  );
}

const APPROVER_KEY = "mom.approver";

function loadApprover() {
  try { return localStorage.getItem(APPROVER_KEY) || ""; } catch { return ""; }
}

function saveApprover(name) {
  try { localStorage.setItem(APPROVER_KEY, name); } catch { /* private mode */ }
}

function Evidence({ quote, segments, onOpen }) {
  const t = useT();
  if (!quote) return null;
  const idx = findSegment(segments, quote);
  const body = (
    <>
      <Quote size={12} aria-hidden="true" className="evidence-icon" />
      <span className="evidence-text">{quote}</span>
      {idx >= 0 && <span className="evidence-time">{t.evidenceAt} {clock(segments[idx].start)}</span>}
    </>
  );
  return idx >= 0
    ? <button type="button" className="evidence link" onClick={() => onOpen(idx)}>{body}</button>
    : <p className="evidence">{body}</p>;
}
