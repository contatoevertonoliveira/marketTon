// Client for the new Django/DRF intelligence backend (server/), kept on its
// own port and separate from the legacy FastAPI backend (API in App.jsx) so
// the two stacks don't collide while both exist.
export const INTEL_API = "http://127.0.0.1:8001/api";

async function request(path, options) {
  const res = await fetch(`${INTEL_API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (data && (data.detail || JSON.stringify(data))) || res.statusText;
    throw new Error(detail);
  }
  return data;
}

export const getJSON = (path) => request(path);
export const postJSON = (path, body) => request(path, { method: "POST", body: JSON.stringify(body || {}) });
