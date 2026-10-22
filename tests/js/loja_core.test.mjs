// Teste do validador da loja pública: só o que a vitrine precisa sobrevive; o resto é descartado.
import assert from "node:assert/strict";
import test from "node:test";
import { cleanSnapshot, MAX_ITEMS } from "../../site/netlify/functions/lib/loja-core.mjs";

const item = (over = {}) => ({
  id: "p1", title: "  Garrafa   Térmica  ", image: "https://cf.shopee.com.br/file/abc", url: "https://felixsystems.com.br/r/abc1234",
  category: "Casa", marketplace: "shopee", marketplace_name: "Shopee", price: 50, original_price: 70, price_date: "2026-10-22",
  rating: 4.84, sold: 120, highlight: true, tracked: true, ...over,
});

test("mantém o que a loja precisa e arruma os textos", () => {
  const s = cleanSnapshot({ items: [item()], store: { name: "Mural na Web", disclosure: "aviso" } });
  assert.equal(s.items.length, 1);
  assert.equal(s.items[0].title, "Garrafa Térmica");
  assert.equal(s.items[0].rating, 4.8);
  assert.deepEqual(s.categories, [{ name: "Casa", count: 1 }]);
  assert.equal(s.store.disclosure, "aviso");
});

test("campos internos nunca passam (comissão, custo, pontuação)", () => {
  const s = cleanSnapshot({ items: [item({ commission_pct: 81.5, cost: 3, score: 9, affiliate_commission_pct: 80, internal: "x" })] });
  const keys = Object.keys(s.items[0]);
  assert.ok(!keys.some((k) => /commission|cost|score|internal/.test(k)), keys.join(","));
  assert.ok(!JSON.stringify(s).includes("81.5"));
});

test("só aceita endereços https e descarta itens sem link, foto ou nome", () => {
  const s = cleanSnapshot({
    items: [
      item({ id: "p2", url: "http://inseguro.com/x" }),
      item({ id: "p3", url: "javascript:alert(1)" }),
      item({ id: "p4", image: "data:image/png;base64,AAAA" }),
      item({ id: "p5", title: "   " }),
      item({ id: "../x" }),
      item({ id: "p6" }),
    ],
  });
  assert.deepEqual(s.items.map((i) => i.id), ["p6"]);
});

test("categoria desconhecida vira diversos, números absurdos viram nulo, ids repetidos contam uma vez", () => {
  const s = cleanSnapshot({ items: [item({ category: "Armas", price: -5, rating: 99, sold: "abc" }), item()] });
  assert.equal(s.items.length, 1);
  assert.equal(s.items[0].category, "Achados diversos");
  assert.equal(s.items[0].price, null);
  assert.equal(s.items[0].rating, null);
  assert.equal(s.items[0].sold, null);
});

test("redes sociais: só https e só as conhecidas", () => {
  const s = cleanSnapshot({ items: [item()], store: { socials: { instagram: "https://instagram.com/mural", facebook: "http://x", orkut: "https://orkut.com", youtube: "javascript:1" } } });
  assert.deepEqual(s.store.socials, { instagram: "https://instagram.com/mural" });
});

test("rejeita fotografia inválida ou grande demais", () => {
  assert.throws(() => cleanSnapshot(null), /inválida/);
  assert.throws(() => cleanSnapshot({ items: "x" }), /inválida/);
  const many = Array.from({ length: MAX_ITEMS + 1 }, (_, i) => item({ id: `p${i}` }));
  assert.throws(() => cleanSnapshot({ items: many }), /itens demais/);
});
