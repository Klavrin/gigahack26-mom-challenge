import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useT } from "../i18n.js";
import { clock } from "../util.js";

const LANG_NAMES = { ro: "Română", ru: "Русский", en: "English" };

// Side sheet with the transcript. Shows how much of the meeting was in each
// language, which is the code-switching the ASR is built for.
export default function Transcript({ segments, highlight, onClose }) {
  const t = useT();
  const list = useRef(null);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    addEventListener("keydown", onKey);
    document.body.classList.add("no-scroll");
    return () => { removeEventListener("keydown", onKey); document.body.classList.remove("no-scroll"); };
  }, [onClose]);

  useEffect(() => {
    if (highlight >= 0) list.current?.querySelector(`[data-i="${highlight}"]`)?.scrollIntoView({ block: "center" });
  }, [highlight]);

  const byLang = {};
  let total = 0;
  for (const s of segments) {
    const d = Math.max(0, s.end - s.start);
    byLang[s.lang] = (byLang[s.lang] || 0) + d;
    total += d;
  }
  const shares = Object.entries(byLang).sort((a, b) => b[1] - a[1]);

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="sheet" role="dialog" aria-modal="true" aria-label={t.transcript}
             onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>{t.transcript}</h2>
          <button className="icon-btn" onClick={onClose} aria-label={t.close} autoFocus><X size={20} /></button>
        </header>

        {total > 0 && (
          <div className="lang-share">
            <div className="lang-bar" aria-hidden="true">
              {shares.map(([l, d]) => <i key={l} className={`lang-${l}`} style={{ flexGrow: d }} />)}
            </div>
            <ul className="lang-legend">
              {shares.map(([l, d]) => (
                <li key={l}><span className={`lang-tag lang-${l}`}>{l}</span>{LANG_NAMES[l] || l} {Math.round((d / total) * 100)}%</li>
              ))}
            </ul>
          </div>
        )}

        <ol className="lines" ref={list}>
          {segments.map((s, i) => (
            <li key={i} data-i={i} className={i === highlight ? "hl" : ""}>
              <span className="line-time">{clock(s.start)}</span>
              <span className={`lang-tag lang-${s.lang}`}>{s.lang}</span>
              <span className="line-text" lang={s.lang}>{s.text}</span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
