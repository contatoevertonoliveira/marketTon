// Redirecionador de links curtos: felixsystems.com.br/r/<código> -> link de afiliado, contando o clique.
//
// Privacidade: guarda só data/hora, país aproximado (do próprio Netlify), tipo de dispositivo e o site de
// origem. NÃO guarda IP nem cookie. Robôs e pré-visualizadores de link (WhatsApp, Telegram, Facebook, etc.)
// são redirecionados, mas não contados — senão o número de cliques seria inflado por máquinas.
import { getStore } from "@netlify/blobs";

const BOTS =
  /bot|crawl|spider|slurp|facebookexternalhit|facebot|whatsapp|telegram|slack|discord|preview|embedly|skype|linkedin|pinterest|twitter|curl|wget|python-requests|httpclient|headless|monitor|uptime|lighthouse|inspect|validator|go-http|okhttp\/|java\//i;

function deviceOf(ua) {
  if (/ipad|tablet/i.test(ua)) return "tablet";
  if (/mobi|android|iphone/i.test(ua)) return "mobile";
  return "desktop";
}

function refHost(referrer) {
  try {
    return new URL(referrer).hostname.toLowerCase().replace(/[^a-z0-9.-]/g, "").slice(0, 60) || "direto";
  } catch {
    return "direto";
  }
}

const notFound = () =>
  new Response("Link não encontrado.", {
    status: 404,
    headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" },
  });

export default async (req, context) => {
  const code = String(context.params?.code || "");
  if (!/^[A-Za-z0-9]{4,32}$/.test(code)) return notFound();

  const links = getStore({ name: "links", consistency: "strong" });
  const link = await links.get(code, { type: "json" });
  if (!link?.url) return notFound();

  const ua = req.headers.get("user-agent") || "";
  if (!BOTS.test(ua) && ua) {
    const clicks = getStore({ name: "clicks" });
    const now = new Date();
    const day = now.toISOString().slice(0, 10);
    const cc = (context.geo?.country?.code || "xx").toLowerCase().replace(/[^a-z]/g, "").slice(0, 2) || "xx";
    const rand = Math.random().toString(36).slice(2, 6);
    // Os dados do clique vão na própria chave: listar as chaves já devolve tudo, sem uma leitura por clique.
    const key = `${day}/${code}/${now.getTime()}-${rand}|${deviceOf(ua)}|${cc}|${refHost(req.headers.get("referer") || "")}`;
    try {
      await clicks.set(key, "1");
    } catch {
      // Contar nunca pode impedir o redirecionamento.
    }
  }

  return new Response(null, {
    status: 302,
    headers: { location: link.url, "cache-control": "no-store", "x-robots-tag": "noindex" },
  });
};

export const config = { path: "/r/:code" };
