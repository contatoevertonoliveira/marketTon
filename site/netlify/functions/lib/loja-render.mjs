// Páginas de produto e feed do catálogo da loja (Mural na Web), gerados no servidor a partir do catálogo publicado.
// Por que no servidor: o Facebook, o Instagram e o WhatsApp leem a página sem rodar JavaScript; sem HTML pronto não há prévia nem
// catálogo. TODO dado vem do catálogo e é escapado aqui: nada é inserido no HTML sem passar por `esc`.

export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const BRL = (v) => (v == null ? null : `R$ ${Number(v).toFixed(2).replace(".", ",").replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`);
const ISO_DAY = (d) => (d ? d.split("-").reverse().join("/") : "");
const MARKETPLACE_TEXT = (it) => `${it.marketplace_name || "Marketplace"}`;

export function describe(it) {
  // Frase curta de fatos (ex.: "Na Shopee: nota 5,0") sozinha é descrição fraca: completa com o nome e o contexto da compra.
  if (it.blurb && it.blurb.length >= 80) return it.blurb;
  if (it.blurb) return `${it.title}. ${it.blurb} Achado selecionado pelo Mural na Web; compra, pagamento e entrega no marketplace.`;
  const facts = [it.rating ? `nota ${String(it.rating).replace(".", ",")}` : null, it.sold ? `${it.sold} vendidos` : null].filter(Boolean);
  return `${it.title}, achado selecionado na ${MARKETPLACE_TEXT(it)}${facts.length ? ` (${facts.join(", ")})` : ""}. Compra, pagamento e entrega no marketplace.`;
}

export function findItem(snapshot, id) {
  return (snapshot?.items || []).find((i) => i.id === id) || null;
}

export function renderProductPage(it, store, origin) {
  const url = `${origin}/p/${it.id}`;
  const desc = describe(it);
  const price = BRL(it.price);
  const was = it.original_price && it.price && it.original_price > it.price ? BRL(it.original_price) : null;
  const ld = {
    "@context": "https://schema.org", "@type": "Product", name: it.title, image: it.images && it.images.length > 1 ? it.images : [it.image], description: desc, category: it.category,
    ...(it.price ? { offers: { "@type": "Offer", url, priceCurrency: "BRL", price: it.price, availability: "https://schema.org/InStock" } } : {}),
  };
  const name = store?.name || "Mural na Web";
  return `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(it.title)} | ${esc(name)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${esc(url)}">
<meta property="og:type" content="product">
<meta property="og:site_name" content="${esc(name)}">
<meta property="og:title" content="${esc(it.title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${esc(url)}">
<meta property="og:image" content="${esc(it.image)}">
${it.price ? `<meta property="product:price:amount" content="${esc(Number(it.price).toFixed(2))}">\n<meta property="product:price:currency" content="BRL">` : ""}
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/loja/img/favicon-64.png">
<link rel="stylesheet" href="/loja/loja.css">
<script src="/loja/pixel.js" defer></script>
<script src="/loja/carousel.js" defer></script>
<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, "\\u003c")}</script>
</head>
<body>
<header class="top"><div class="top-in"><a class="brand" href="/" aria-label="${esc(name)}"><img src="/loja/img/logo-96.png" width="56" height="56" alt="${esc(name)}"></a>
<a class="btn btn-soft btn-small" href="/#achados" style="margin-left:auto">Ver todos os achados</a></div></header>
<main class="wrap" style="padding-block:32px 64px">
<article class="sheet-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:28px;background:var(--white);border-radius:16px;overflow:hidden">
${galleryHtml(it)}
<div class="sheet-info" style="padding:24px 28px 28px">
<span class="tag">${esc(it.category)} · ${esc(MARKETPLACE_TEXT(it))}</span>
<h1 style="font-size:var(--s-head)">${esc(it.title)}</h1>
${it.blurb ? `<p>${esc(it.blurb)}</p>` : ""}
<div class="price">${price ? `<b>${esc(price)}</b>` : "<b>Preço na página do marketplace</b>"}${was ? `<s>${esc(was)}</s>` : ""}</div>
<p class="small">${esc([it.rating ? `Nota ${String(it.rating).replace(".", ",")}` : null, it.sold ? `${it.sold} vendidos` : null, it.price_date ? `preço visto em ${ISO_DAY(it.price_date)}` : null].filter(Boolean).join(" · "))}</p>
<p class="small">O preço pode mudar: confira na página do marketplace antes de finalizar. Se você comprar pelo botão abaixo, o Mural recebe uma comissão, sem custo extra para você.</p>
<div class="sheet-actions"><a class="btn btn-red" href="${esc(it.url)}" target="_blank" rel="sponsored noopener">Quero esse na ${esc(MARKETPLACE_TEXT(it))}</a>
<a class="btn btn-soft" href="/#${esc(it.id)}">Ver na loja</a></div>
</div></article>
<p class="notice" style="margin-top:20px">${esc(store?.disclosure || "Participamos de programas de afiliados e podemos receber comissão pelas compras feitas pelos links desta página, sem custo extra para você.")}</p>
</main>
</body>
</html>`;
}

/** Uma foto: imagem estática. Mais de uma: carrossel (rolagem com encaixe funciona até sem JavaScript). */
export function galleryHtml(it) {
  const list = Array.isArray(it.images) && it.images.length > 1 ? it.images : null;
  if (!list) {
    return `<div class="sheet-art" style="min-height:320px;position:relative"><img src="${esc(it.image)}" alt="${esc(it.title)}" referrerpolicy="no-referrer" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover"></div>`;
  }
  const slides = list.map((src, i) => `<img src="${esc(src)}" alt="${esc(it.title)} (foto ${i + 1} de ${list.length})" referrerpolicy="no-referrer"${i === 0 ? "" : ' loading="lazy"'}>`).join("");
  return `<div class="sheet-art" style="min-height:320px;position:relative"><div class="car" aria-roledescription="carrossel" aria-label="Fotos de ${esc(it.title)}"><div class="car-track">${slides}</div></div></div>`;
}

export function renderNotFound() {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Achado não encontrado | Mural na Web</title><meta name="robots" content="noindex"><link rel="stylesheet" href="/loja/loja.css"></head><body><main class="wrap" style="padding-block:64px"><h1>Esse achado saiu da vitrine</h1><p class="lead">Ele pode ter acabado ou mudado de preço. Veja os outros achados do Mural.</p><p style="margin-top:20px"><a class="btn btn-red" href="/">Ver os achados</a></p></main></body></html>`;
}

const xml = (v) => esc(v).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");

export function renderFeed(snapshot, origin) {
  const store = snapshot?.store || {};
  const items = (snapshot?.items || [])
    .filter((it) => it.price && it.image && it.url)
    .map((it) => {
      const sale = it.original_price && it.original_price > it.price;
      return `<item>
<g:id>${xml(it.id)}</g:id>
<g:title>${xml(it.title.slice(0, 150))}</g:title>
<g:description>${xml(describe(it).slice(0, 4900))}</g:description>
<g:link>${xml(`${origin}/p/${it.id}`)}</g:link>
<g:image_link>${xml(it.image)}</g:image_link>
<g:availability>in stock</g:availability>
<g:condition>new</g:condition>
<g:price>${(sale ? it.original_price : it.price).toFixed(2)} BRL</g:price>
${sale ? `<g:sale_price>${it.price.toFixed(2)} BRL</g:sale_price>` : ""}
<g:brand>${xml(store.name || "Mural na Web")}</g:brand>
<g:product_type>${xml(it.category)}</g:product_type>
</item>`;
    })
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
<channel>
<title>${xml(store.name || "Mural na Web")}</title>
<link>${xml(origin)}</link>
<description>${xml(store.tagline || "Achados selecionados")}</description>
${items}
</channel>
</rss>`;
}
