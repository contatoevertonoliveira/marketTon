// API administrativa dos links curtos. Só o marketTon usa, com um token secreto (Authorization: Bearer ...).
//   POST   /api/links               {code, url}  registra um link curto (url precisa ser https)
//   DELETE /api/links?code=abc123                 apaga
//   GET    /api/links/clicks?since=AAAA-MM-DD[&until=AAAA-MM-DD]   cliques do período (um evento por clique)
//   GET    /api/links/ping                        confere o token
import { getStore } from "@netlify/blobs";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

// Em vez de uma variável de ambiente (o painel do Netlify é opcional aqui), a função guarda só o HASH SHA-256 do
// token. Como o token é aleatório e longo, o hash não permite recuperá-lo. Para trocar o token: gere outro, troque
// este hash e publique de novo (o marketTon guarda o token em Integrações > Encurtador de links).
const TOKEN_SHA256 = "092de13bd035de3a0873fe0f40c22a1f33d90bbc309920ec095be1d91752efe2";

async function authorized(req) {
  const given = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!given) return false;
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(given));
  const hex = [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const expected = Netlify.env.get("LINKS_ADMIN_TOKEN_SHA256") || TOKEN_SHA256;
  if (hex.length !== expected.length) return false;
  let diff = 0; // comparação em tempo constante
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ hex.charCodeAt(i);
  return diff === 0;
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function* days(since, until) {
  const end = new Date(`${until}T00:00:00Z`);
  for (let d = new Date(`${since}T00:00:00Z`); d <= end; d = new Date(d.getTime() + 86400000)) {
    yield d.toISOString().slice(0, 10);
  }
}

export default async (req) => {
  if (!(await authorized(req))) return json({ error: "não autorizado" }, 401);
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "");
  const links = getStore({ name: "links", consistency: "strong" });

  if (path === "/api/links/ping") return json({ ok: true });

  if (path === "/api/links" && req.method === "POST") {
    let body;
    try {
      body = await req.json();
    } catch {
      return json({ error: "JSON inválido" }, 400);
    }
    const code = String(body.code || "");
    let dest;
    try {
      dest = new URL(String(body.url || ""));
    } catch {
      return json({ error: "url inválida" }, 400);
    }
    if (!/^[A-Za-z0-9]{4,32}$/.test(code)) return json({ error: "código inválido" }, 400);
    if (dest.protocol !== "https:") return json({ error: "o destino precisa ser https" }, 400);
    if (await links.get(code)) return json({ error: "código já existe" }, 409);
    await links.setJSON(code, { url: dest.toString(), created: new Date().toISOString() });
    return json({ ok: true, code }, 201);
  }

  if (path === "/api/links" && req.method === "DELETE") {
    const code = url.searchParams.get("code") || "";
    if (!/^[A-Za-z0-9]{4,32}$/.test(code)) return json({ error: "código inválido" }, 400);
    await links.delete(code);
    return json({ ok: true });
  }

  if (path === "/api/links/clicks" && req.method === "GET") {
    const today = new Date().toISOString().slice(0, 10);
    const since = url.searchParams.get("since") || today;
    const until = url.searchParams.get("until") || today;
    if (!DAY.test(since) || !DAY.test(until) || since > until) return json({ error: "período inválido" }, 400);
    const clicks = getStore({ name: "clicks" });
    const events = [];
    let truncated = false;
    outer: for (const day of days(since, until)) {
      for await (const page of clicks.list({ prefix: `${day}/`, paginate: true })) {
        for (const { key } of page.blobs) {
          const [head, device, country, referrer, campaign] = key.split("|");
          const [, code, stamp] = head.split("/");
          const t = Number(stamp.split("-")[0]);
          events.push({ id: key, code, t: new Date(t).toISOString(), device, country, referrer, ...(campaign ? { campaign } : {}) });
          if (events.length >= 5000) {
            truncated = true;
            break outer;
          }
        }
      }
    }
    return json({ since, until, count: events.length, truncated, events });
  }

  return json({ error: "rota desconhecida" }, 404);
};

export const config = { path: ["/api/links", "/api/links/*"] };
