// Client for the real backend (FastAPI + PostgreSQL, backend/main.py), which
// requires a JWT on every request. Replaces intelApi.js (talked to the
// retired Django prototype).
export const API_BASE = "http://127.0.0.1:8000";

const ACCESS_KEY = "aisys_access_token";
const REFRESH_KEY = "aisys_refresh_token";

export function getTokens() {
  return {
    access: localStorage.getItem(ACCESS_KEY),
    refresh: localStorage.getItem(REFRESH_KEY),
  };
}

function setTokens({ access_token, refresh_token }) {
  if (access_token) localStorage.setItem(ACCESS_KEY, access_token);
  if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export function isLoggedIn() {
  return !!getTokens().access;
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.detail || "login falhou");
  }
  setTokens(data);
  return data;
}

export function logout() {
  clearTokens();
}

async function tryRefresh() {
  const { refresh } = getTokens();
  if (!refresh) return false;
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  setTokens(data);
  return true;
}

let onAuthExpired = () => {};
export function setAuthExpiredHandler(fn) {
  onAuthExpired = fn;
}

async function request(path, options = {}, _retried = false) {
  const { access } = getTokens();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(access ? { Authorization: `Bearer ${access}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (res.status === 401 && !_retried) {
    const refreshed = await tryRefresh();
    if (refreshed) return request(path, options, true);
    clearTokens();
    onAuthExpired();
    throw new Error("sessão expirada — faça login novamente");
  }

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || res.statusText;
    throw new Error(message);
  }
  return data;
}

export const getJSON = (path) => request(path);
export const postJSON = (path, body) => request(path, { method: "POST", body: JSON.stringify(body || {}) });
export const putJSON = (path, body) => request(path, { method: "PUT", body: JSON.stringify(body || {}) });
