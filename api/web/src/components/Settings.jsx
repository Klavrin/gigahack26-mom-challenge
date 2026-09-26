import { useEffect } from "react";
import { ExternalLink, X } from "lucide-react";
import { useT } from "../i18n.js";
import { MEETING_TYPES, healthLevel } from "../util.js";

// Everything technical lives here, out of the doctors' way.
export default function Settings({ settings, onChange, health, onClose }) {
  const t = useT();
  const set = (patch) => onChange({ ...settings, ...patch });
  const level = healthLevel(health);
  const host = location.hostname;

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    addEventListener("keydown", onKey);
    document.body.classList.add("no-scroll");
    return () => { removeEventListener("keydown", onKey); document.body.classList.remove("no-scroll"); };
  }, [onClose]);

  const where = (n) => {
    if (n.status === "mock") return t.sState.mock;
    if (n.where === "local") return t.sThisMachine;
    try { return new URL(n.where).host; } catch { return n.where; }
  };

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="sheet settings" role="dialog" aria-modal="true" aria-label={t.settings}
             onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>{t.settings}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t.close} autoFocus><X size={20} /></button>
        </header>

        <section className="s-section">
          <h3 className="eyebrow">{t.sGeneral}</h3>
          <div className="s-row">
            <span>{t.sLanguage}</span>
            <div className="segmented">
              {[["ro", "Română"], ["en", "English"]].map(([k, label]) => (
                <button key={k} className={settings.lang === k ? "on" : ""} onClick={() => set({ lang: k })}>{label}</button>
              ))}
            </div>
          </div>
          <label className="s-row">
            <span>{t.sDefaultType}</span>
            <select value={settings.defaultType} onChange={(e) => set({ defaultType: e.target.value })}>
              {MEETING_TYPES.map((k) => <option key={k} value={k}>{t.types[k]}</option>)}
            </select>
          </label>
        </section>

        <section className="s-section">
          <h3 className="eyebrow">{t.sSystem}</h3>
          {health?.mock && <p className="notice small">{t.sMock}</p>}
          {level === "down" && <p className="notice warn small">{t.sSomeDown}</p>}
          {level === "up" && <p className="muted small">{t.sAllUp}</p>}
          <ul className="nodes">
            {["asr", "llm", "n8n"].map((k) => {
              const n = health?.nodes?.[k] || { status: "down" };
              return (
                <li key={k}>
                  <span className={`node-dot ${n.status}`} aria-hidden="true" />
                  <div>
                    <p>{t.sNodes[k]}</p>
                    <p className="muted small">
                      {[n.model, n.device, health ? where(n) : null].filter(Boolean).join(" · ")}
                      {n.detail ? ` · ${n.detail}` : ""}
                    </p>
                  </div>
                  <span className={`chip ${n.status}`}>{t.sState[n.status]}</span>
                </li>
              );
            })}
          </ul>
          {health && <p className="muted small">{t.sAsrMode}: <code>{health.asr_mode}</code></p>}
        </section>

        <section className="s-section">
          <h3 className="eyebrow">{t.sTools}</h3>
          <ul className="tools">
            <li><a href={`http://${host}:8025`} target="_blank" rel="noreferrer">{t.sInbox} <ExternalLink size={14} /></a></li>
            <li><a href={`http://${host}:5678`} target="_blank" rel="noreferrer">{t.sWorkflow} <ExternalLink size={14} /></a></li>
            <li><a href="/api/health" target="_blank" rel="noreferrer">{t.sHealth} <ExternalLink size={14} /></a></li>
          </ul>
        </section>

        <section className="s-section">
          <h3 className="eyebrow">{t.sPrivacy}</h3>
          <p className="muted small">{t.sPrivacyText}</p>
        </section>
      </aside>
    </div>
  );
}
