// API da loja pública (Mural na Web).
//   GET  /api/loja/catalogo   público: o catálogo publicado (a loja lê daqui)
//   GET  /api/loja/ping       confere o token do marketTon
//   POST /api/loja/publicar   o marketTon envia a fotografia do catálogo (Authorization: Bearer ...)
import { getStore } from "@netlify/blobs";
import { cleanSnapshot } from "./lib/loja-core.mjs";

const json = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", ...extra } });

// Só o HASH SHA-256 do token fica no código (o marketTon guarda o token em Integrações > Vitrine pública).
// Para trocar: gere outro token, troque este hash e publique de novo. `LOJA_ADMIN_TOKEN_SHA256` tem prioridade, se existir.
const TOKEN_SHA256 = "__TOKEN_SHA256__";

async function authorized(req) {
  const given = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!given) return false;
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(given));
  const hex = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const expected = Netlify.env.get("LOJA_ADMIN_TOKEN_SHA256") || TOKEN_SHA256;
  if (hex.length !== expected.length) return false;
  let diff = 0; // comparação em tempo constante
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ hex.charCodeAt(i);
  return diff === 0;
}

export default async (req) => {
  const path = new URL(req.url).pathname.replace(/\/+$/, "");
  const store = getStore({ name: "loja", consistency: "strong" });

  if (path === "/api/loja/catalogo" && req.method === "GET") {
    const data = await store.get("catalogo", { type: "json" });
    if (!data) return json({ error: "a vitrine ainda não foi publicada" }, 404, { "cache-control": "no-store" });
    return json(data, 200, { "cache-control": "public, max-age=60, s-maxage=60" });
  }

  if (!(await authorized(req))) return json({ error: "não autorizado" }, 401, { "cache-control": "no-store" });

  if (path === "/api/loja/ping") return json({ ok: true });

  if (path === "/api/loja/publicar" && req.method === "POST") {
    let body;
    try {
      body = await req.json();
    } catch {
      return json({ error: "JSON inválido" }, 400);
    }
    let snapshot;
    try {
      snapshot = cleanSnapshot(body);
    } catch (e) {
      return json({ error: e.message }, 422);
    }
    if (!snapshot.items.length) return json({ error: "nenhum item válido para publicar" }, 422);
    await store.setJSON("catalogo", snapshot);
    return json({ ok: true, count: snapshot.items.length, published_at: snapshot.published_at });
  }

  return json({ error: "rota desconhecida" }, 404);
};

export const config = { path: ["/api/loja/catalogo", "/api/loja/ping", "/api/loja/publicar"] };
