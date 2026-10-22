// Páginas públicas geradas do catálogo publicado:
//   GET /p/<id>              página do produto (com prévia para Facebook/Instagram/WhatsApp e dados estruturados)
//   GET /api/loja/feed.xml   feed de produtos para o Catálogo da Meta (Commerce Manager)
import { getStore } from "@netlify/blobs";
import { findItem, renderFeed, renderNotFound, renderProductPage } from "./lib/loja-render.mjs";

const html = (body, status = 200, cache = "public, max-age=300, s-maxage=300") =>
  new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": cache } });

export default async (req, context) => {
  const url = new URL(req.url);
  const snapshot = await getStore({ name: "loja", consistency: "strong" }).get("catalogo", { type: "json" });
  const origin = url.origin;

  if (url.pathname === "/api/loja/feed.xml") {
    if (!snapshot) return new Response("sem catálogo", { status: 404, headers: { "cache-control": "no-store" } });
    return new Response(renderFeed(snapshot, origin), {
      headers: { "content-type": "application/xml; charset=utf-8", "cache-control": "public, max-age=900, s-maxage=900" },
    });
  }

  const id = String(context.params?.id || "");
  if (!/^p\d{1,12}$/.test(id) || !snapshot) return html(renderNotFound(), 404, "no-store");
  const item = findItem(snapshot, id);
  if (!item) return html(renderNotFound(), 404, "no-store");
  return html(renderProductPage(item, snapshot.store, origin));
};

export const config = { path: ["/p/:id", "/api/loja/feed.xml"] };
