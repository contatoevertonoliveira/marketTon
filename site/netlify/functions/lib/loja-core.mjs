// Validação da fotografia do catálogo recebida do marketTon. Só o que a loja pública precisa passa daqui:
// textos curtos, números, categorias e endereços https. Qualquer outra coisa é descartada (a loja nunca confia no que recebe).

export const MAX_ITEMS = 500;
export const CATEGORIES = ["Eletrônicos", "Casa", "Moda", "Beleza", "Games", "Pet", "Cursos", "Achados diversos"];
export const SOCIAL_KEYS = ["facebook", "instagram", "youtube", "whatsapp", "telegram", "tiktok"];

const text = (v, max) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim().slice(0, max) : "");
const https = (v) => {
  if (typeof v !== "string" || v.length > 1000) return "";
  try {
    const u = new URL(v);
    return u.protocol === "https:" ? u.toString() : "";
  } catch {
    return "";
  }
};
const num = (v, { min = 0, max = 1e7, digits = 2 } = {}) => {
  const n = Number(v);
  return Number.isFinite(n) && n >= min && n <= max ? Number(n.toFixed(digits)) : null;
};
const day = (v) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null);

export function cleanItem(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = typeof raw.id === "string" && /^p\d{1,12}$/.test(raw.id) ? raw.id : "";
  const title = text(raw.title, 160);
  const url = https(raw.url);
  const image = https(raw.image);
  if (!id || !title || !url || !image) return null; // sem link, sem foto ou sem nome: não entra
  const category = CATEGORIES.includes(raw.category) ? raw.category : "Achados diversos";
  return {
    id,
    title,
    image,
    url,
    category,
    marketplace: text(raw.marketplace, 32),
    marketplace_name: text(raw.marketplace_name, 40) || "Marketplace",
    blurb: text(raw.blurb, 280) || null,
    price: num(raw.price),
    original_price: num(raw.original_price),
    price_date: day(raw.price_date),
    rating: num(raw.rating, { max: 5, digits: 1 }),
    sold: num(raw.sold, { max: 1e9, digits: 0 }),
    highlight: raw.highlight === true,
    tracked: raw.tracked === true,
  };
}

export function cleanSnapshot(raw) {
  if (!raw || typeof raw !== "object" || !Array.isArray(raw.items)) throw new Error("fotografia inválida: faltam os itens");
  if (raw.items.length > MAX_ITEMS) throw new Error(`itens demais (máximo ${MAX_ITEMS})`);
  const seen = new Set();
  const items = [];
  for (const r of raw.items) {
    const item = cleanItem(r);
    if (item && !seen.has(item.id)) {
      seen.add(item.id);
      items.push(item);
    }
  }
  const store = raw.store && typeof raw.store === "object" ? raw.store : {};
  const socials = {};
  for (const k of SOCIAL_KEYS) {
    const u = https(store.socials?.[k]);
    if (u) socials[k] = u;
  }
  const counts = new Map();
  for (const it of items) counts.set(it.category, (counts.get(it.category) || 0) + 1);
  return {
    version: 1,
    generated_at: text(raw.generated_at, 40) || new Date().toISOString(),
    published_at: new Date().toISOString(),
    store: {
      name: text(store.name, 60) || "Mural na Web",
      tagline: text(store.tagline, 200),
      subtitle: text(store.subtitle, 240),
      disclosure: text(store.disclosure, 900),
      socials,
    },
    categories: CATEGORIES.filter((c) => counts.has(c)).map((name) => ({ name, count: counts.get(name) })),
    items,
  };
}
