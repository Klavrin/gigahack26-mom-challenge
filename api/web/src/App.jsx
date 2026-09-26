import { useCallback, useEffect, useState } from "react";
import { Lock, Settings as Gear } from "lucide-react";
import { api } from "./api.js";
import { I18n, STRINGS } from "./i18n.js";
import { healthLevel } from "./util.js";
import Home from "./components/Home.jsx";
import Job from "./components/Job.jsx";
import Settings from "./components/Settings.jsx";

const SETTINGS_KEY = "mom.settings";
const DEFAULTS = { lang: "ro", defaultType: "medical" };

function loadSettings() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }; }
  catch { return DEFAULTS; }
}

const jobFromHash = () => location.hash.match(/job=([\w-]+)/)?.[1] || null;

// Polls /api/health; the result only surfaces in Settings and as a dot on its icon.
function useHealth() {
  const [health, setHealth] = useState(null);
  useEffect(() => {
    let alive = true;
    const tick = () => api.health().then((h) => alive && setHealth(h)).catch(() => alive && setHealth(null));
    tick();
    const id = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return health;
}

export default function App() {
  const [settings, setSettings] = useState(loadSettings);
  const [jobId, setJobId] = useState(jobFromHash);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const health = useHealth();
  const t = STRINGS[settings.lang] || STRINGS.ro;

  useEffect(() => {
    document.documentElement.lang = settings.lang;
    document.title = t.brand;
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch { /* private mode */ }
  }, [settings, t]);

  useEffect(() => {
    const sync = () => setJobId(jobFromHash());
    addEventListener("popstate", sync);
    addEventListener("hashchange", sync);
    return () => { removeEventListener("popstate", sync); removeEventListener("hashchange", sync); };
  }, []);

  const open = useCallback((id) => {
    history.pushState(null, "", id ? `#job=${id}` : location.pathname);
    setJobId(id);
    scrollTo({ top: 0 });
  }, []);

  const level = healthLevel(health);

  return (
    <I18n.Provider value={t}>
      <div className="app">
        <header className="topbar">
          <button className="brand" onClick={() => open(null)}>
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
            {t.brand}
          </button>
          <button className="icon-btn" onClick={() => setSettingsOpen(true)} aria-label={t.settings} title={t.settings}>
            <Gear size={20} strokeWidth={1.75} />
            {level !== "up" && <span className={`status-dot ${level}`} aria-hidden="true" />}
          </button>
        </header>

        <main className="content">
          {jobId
            ? <Job key={jobId} id={jobId} onNew={() => open(null)} lang={settings.lang} />
            : <Home onStarted={open} defaultType={settings.defaultType} lang={settings.lang} />}
        </main>

        <footer className="footer">
          <Lock size={13} strokeWidth={2} aria-hidden="true" /> {t.privacy}
        </footer>

        {settingsOpen && (
          <Settings settings={settings} onChange={setSettings} health={health}
                    onClose={() => setSettingsOpen(false)} />
        )}
      </div>
    </I18n.Provider>
  );
}
