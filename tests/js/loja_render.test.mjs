// Páginas de produto e feed da loja: tudo escapado, campos obrigatórios do catálogo da Meta, sem dados internos.
import assert from "node:assert/strict";
import test from "node:test";
import { esc, findItem, renderFeed, renderNotFound, renderProductPage } from "../../site/netlify/functions/lib/loja-render.mjs";

const item = (over = {}) => ({
  id: "p33", title: 'Garrafa "Térmica" <script>alert(1)</script> & Cia', image: "https://cf.shopee.com.br/file/a", url: "https://felixsystems.com.br/r/abc1234",
  category: "Casa", marketplace: "shopee", marketplace_name: "Shopee", price: 59, original_price: 79, price_date: "2026-10-22", rating: 4.8, sold: 15, blurb: null, ...over,
});
const snap = (items) => ({ store: { name: "Mural na Web", tagline: "Boas descobertas", disclosure: "Aviso de afiliado" }, items });

test("a página do produto escapa tudo e traz a prévia para as redes", () => {
  const html = renderProductPage(item(), snap([]).store, "https://mural.felixsystems.com.br");
  assert.ok(!html.includes("<script>alert(1)"), "script do título não pode passar");
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes('property="og:title"') && html.includes('property="og:image" content="https://cf.shopee.com.br/file/a"'));
  assert.ok(html.includes('<link rel="canonical" href="https://mural.felixsystems.com.br/p/p33">'));
  assert.ok(html.includes('rel="sponsored noopener"') && html.includes("https://felixsystems.com.br/r/abc1234"), "o botão leva ao link rastreado de afiliado");
  assert.ok(html.includes("R$ 59,00") && html.includes("R$ 79,00") && html.includes("Aviso de afiliado"));
  assert.equal((html.match(/application\/ld\+json/g) || []).length, 1);
});

test("o feed segue o formato do Catálogo da Meta e só leva itens completos", () => {
  const xml = renderFeed(snap([item(), item({ id: "p34", price: null }), item({ id: "p35", image: "" })]), "https://mural.felixsystems.com.br");
  assert.equal((xml.match(/<item>/g) || []).length, 1);
  for (const tag of ["g:id", "g:title", "g:description", "g:link", "g:image_link", "g:availability", "g:condition", "g:price", "g:brand"]) assert.ok(xml.includes(`<${tag}>`), tag);
  assert.ok(xml.includes("<g:link>https://mural.felixsystems.com.br/p/p33</g:link>"), "o link do feed é a página do produto na loja");
  assert.ok(xml.includes("<g:price>79.00 BRL</g:price>") && xml.includes("<g:sale_price>59.00 BRL</g:sale_price>"));
  assert.ok(!xml.includes("<script>") && !/commission|comiss/i.test(xml));
});

test("helpers", () => {
  assert.equal(esc(`<&"'>`), "&lt;&amp;&quot;&#39;&gt;");
  assert.equal(findItem(snap([item()]), "p33").id, "p33");
  assert.equal(findItem(snap([item()]), "p99"), null);
  assert.ok(renderNotFound().includes("saiu da vitrine"));
});


test("a página do produto carrega o script do pixel (que só liga depois do aceite)", () => {
  const html = renderProductPage(item(), snap([item()]).store, "https://mural.felixsystems.com.br");
  assert.ok(html.includes('src="/loja/pixel.js"'));
  assert.ok(!html.includes("fbevents.js") && !html.includes("fbq("), "nada da Meta direto no HTML: só pelo script, depois do aceite");
});

test("a página do produto vira carrossel só quando há mais de uma foto", () => {
  const store = snap([]).store;
  const one = renderProductPage(item(), store, "https://mural.felixsystems.com.br");
  assert.ok(!one.includes('class="car"') && !one.includes("car-track"));
  const many = renderProductPage(item({ images: ["https://cf.shopee.com.br/file/a", "https://x/2.jpg", "https://x/3.jpg"] }), store, "https://mural.felixsystems.com.br");
  assert.equal((many.match(/<img src="https:\/\/(cf\.shopee\.com\.br|x)\//g) || []).length, 3);
  assert.ok(many.includes("car-track") && many.includes('src="/loja/carousel.js"') && many.includes("foto 2 de 3"));
  assert.ok(many.includes('"image":["https://cf.shopee.com.br/file/a","https://x/2.jpg","https://x/3.jpg"]'), "os dados estruturados levam todas as fotos");
});
