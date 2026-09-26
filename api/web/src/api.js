async function json(resp) {
  if (!resp.ok) {
    let detail;
    try { detail = (await resp.json()).detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : resp.statusText || `HTTP ${resp.status}`);
  }
  return resp.json();
}

const get = (url) => fetch(url).then(json);

export const api = {
  health: () => get("/api/health"),
  recent: () => get("/api/jobs"),
  job: (id) => get(`/api/jobs/${id}`),
  mom: (id) => get(`/api/jobs/${id}/mom.json`),
  segments: (id) => get(`/api/jobs/${id}/segments.json`),

  send: (id, body) =>
    fetch(`/api/jobs/${id}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json),

  // XHR instead of fetch so large recordings show upload progress.
  create(blob, filename, meetingType, meetingDate, onProgress) {
    const form = new FormData();
    form.append("file", blob, filename);
    form.append("meeting_type", meetingType);
    form.append("meeting_date", meetingDate);
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        let body;
        try { body = JSON.parse(xhr.responseText); } catch { body = {}; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new Error(body.detail || `HTTP ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("network"));
      xhr.send(form);
    });
  },
};
