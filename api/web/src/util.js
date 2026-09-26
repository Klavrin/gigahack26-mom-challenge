export const MEETING_TYPES = ["medical", "executive", "administrative"];

export function isoDate(d = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatDate(iso, lang) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(lang === "ro" ? "ro-RO" : "en-GB", {
    day: "numeric", month: "long", year: "numeric",
  }).format(new Date(y, m - 1, d));
}

// 75 -> "1:15", 3725 -> "1:02:05"
export function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? `${h}:` : "") + `${mm}:${String(r).padStart(2, "0")}`;
}

const norm = (s) => s.toLowerCase().normalize("NFC").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

// Index of the transcript segment an evidence quote came from, or -1.
export function findSegment(segments, quote) {
  if (!quote || !segments?.length) return -1;
  const q = norm(quote);
  const probe = q.slice(0, 32);
  let idx = segments.findIndex((s) => norm(s.text).includes(probe));
  if (idx < 0) {
    const words = q.split(" ").filter((w) => w.length > 3);
    let best = 0;
    segments.forEach((s, i) => {
      const t = norm(s.text);
      const hits = words.filter((w) => t.includes(w)).length;
      if (hits > best && hits >= Math.min(3, words.length)) { best = hits; idx = i; }
    });
  }
  return idx;
}

export function initials(name) {
  return name
    .replace(/^(dr|prof|dna|dl)\.?\s+/i, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

export function healthLevel(health) {
  if (!health) return "down";
  const states = Object.values(health.nodes).map((n) => n.status);
  if (states.includes("down")) return "down";
  return states.includes("mock") ? "mock" : "up";
}
