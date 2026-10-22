// Mural na Web — vitrine pública. Sem dependências, sem cookies, sem rastreadores.
// Os dados vêm de /api/loja/catalogo (publicado pelo marketTon). O "Meu mural" fica só neste aparelho (localStorage).
(() => {
  "use strict";

  const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const COMPACT = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
  const BAG_KEY = "mural:fixados";
  const PAGE = 12;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SOCIAL_LABELS = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", whatsapp: "Grupo no WhatsApp", telegram: "Telegram", tiktok: "TikTok" };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
    return el;
  }
  const svg = (path, size = 20) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    el.setAttribute("viewBox", "0 0 24 24"); el.setAttribute("width", size); el.setAttribute("height", size); el.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", path); p.setAttribute("fill", "currentColor"); el.append(p);
    return el;
  };
  const PIN = "M15 3l6 6-3 1-3.5 3.5.5 4.5-1.5 1.5-4-4-5 5-1-1 5-5-4-4L6 9.5l4.5.5L14 6.5z";
  const SHARE = "M18 16a3 3 0 0 0-2.4 1.2l-6.3-3.2a3 3 0 0 0 0-2l6.3-3.2A3 3 0 1 0 15 7a3 3 0 0 0 .1.8L8.8 11A3 3 0 1 0 8.8 13l6.3 3.2A3 3 0 1 0 18 16z";

  const safeUrl = (u) => (typeof u === "string" && u.startsWith("https://") ? u : "");
  const money = (v) => (v == null ? null : BRL.format(v));
  const dayBR = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const off = (it) => (it.original_price && it.price && it.original_price > it.price ? Math.round((1 - it.price / it.original_price) * 100) : 0);

  // ---------------- estado ----------------
  let data = { items: [], categories: [], store: {} };
  const byId = new Map();
  const state = { q: "", cat: "", preco: "", ordem: "", shown: PAGE };

  let bag = [];
  try { bag = JSON.parse(localStorage.getItem(BAG_KEY) || "[]").filter((x) => typeof x === "string"); } catch { bag = []; }
  const saveBag = () => { try { localStorage.setItem(BAG_KEY, JSON.stringify(bag)); } catch { /* sem armazenamento: segue em memória */ } };
  const inBag = (id) => bag.includes(id);

  function toast(text) {
    const t = $("#toast");
    t.textContent = text; t.classList.add("on");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 2200);
  }

  function paintBag(bump) {
    $$("[data-bag-count]").forEach((el) => {
      el.textContent = String(bag.length);
      if (bump && !reduced) { el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); }
    });
    $$("[data-pin]").forEach((b) => {
      const on = inBag(b.dataset.pin);
      b.setAttribute("aria-pressed", String(on));
      b.setAttribute("aria-label", on ? "Tirar do meu mural" : "Fixar no meu mural");
      b.title = on ? "Tirar do meu mural" : "Fixar no meu mural";
      if (b.dataset.label) b.lastChild.textContent = on ? "Fixado no mural" : "Fixar no mural";
    });
  }
  function togglePin(id) {
    const was = inBag(id);
    bag = was ? bag.filter((x) => x !== id) : [...bag, id];
    saveBag(); paintBag(true);
    toast(was ? "Tirado do seu mural" : "Fixado no seu mural");
    if ($("#sacola").open) renderBag();
  }

  async function share(it) {
    const url = `${location.origin}${location.pathname}#${it.id}`;
    try {
      if (navigator.share) { await navigator.share({ title: it.title, text: `${it.title} no Mural na Web`, url }); return; }
      await navigator.clipboard.writeText(url);
      toast("Link copiado");
    } catch { /* cancelou o compartilhamento */ }
  }

  // ---------------- carga ----------------
  async function load() {
    try {
      const r = await fetch("/api/loja/catalogo", { cache: "no-cache" });
      if (r.ok) return await r.json();
    } catch { /* sem rede */ }
    return null;
  }

  // ---------------- cartões ----------------
  function card(it, i) {
    const pct = off(it);
    const img = h("button", { class: "card-img", type: "button", "aria-label": `Ver detalhes: ${it.title}`, onclick: () => openProduct(it.id) },
      h("img", { src: safeUrl(it.image), alt: "", width: 400, height: 400, loading: i < 6 ? "eager" : "lazy", decoding: "async", referrerpolicy: "no-referrer" }));
    const wrapImg = h("div", { style: "position:relative" }, img,
      pct >= 5 ? h("span", { class: "off", text: `-${pct}%` }) : null,
      h("div", { class: "acts" },
        h("button", { class: "icon-btn", type: "button", "data-pin": it.id, onclick: () => togglePin(it.id) }, svg(PIN)),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Compartilhar", title: "Compartilhar", onclick: () => share(it) }, svg(SHARE))));
    const price = money(it.price);
    const meta = [it.rating ? `Nota ${String(it.rating).replace(".", ",")}` : null, it.sold ? `${COMPACT.format(it.sold)} vendidos` : null].filter(Boolean).join(" · ");
    return h("article", { class: "card rv", style: `--i:${i % 5}` }, wrapImg,
      h("div", { class: "card-body" },
        h("span", { class: "tag", text: it.marketplace_name }),
        h("h3", {}, h("a", { href: `#${it.id}`, onclick: (e) => { e.preventDefault(); openProduct(it.id); } }, it.title)),
        h("div", { class: "price" }, price ? h("b", { text: price }) : h("b", { text: "Ver preço" }), it.original_price && pct ? h("s", { text: money(it.original_price) }) : null),
        h("p", { class: "meta", text: meta }),
        h("a", { class: "btn btn-red", href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin", "aria-label": `Quero esse: ${it.title}, na ${it.marketplace_name}` }, "Quero esse")));
  }

  // ---------------- filtros e feed ----------------
  function filtered() {
    const q = norm(state.q).split(/\s+/).filter(Boolean);
    let list = data.items.filter((it) => {
      if (state.cat ? it.category !== state.cat : it.category === "Cursos") return false;
      if (state.preco && !(it.price != null && it.price <= Number(state.preco))) return false;
      const hay = norm(`${it.title} ${it.category} ${it.marketplace_name} ${it.blurb || ""}`);
      return q.every((w) => hay.includes(w));
    });
    if (state.ordem === "menor") list = [...list].sort((a, b) => (a.price ?? 1e9) - (b.price ?? 1e9));
    else if (state.ordem === "desconto") list = [...list].sort((a, b) => off(b) - off(a));
    else if (state.ordem === "vendas") list = [...list].sort((a, b) => (b.sold || 0) - (a.sold || 0));
    else list = [...list].sort((a, b) => Number(b.highlight) - Number(a.highlight));
    return list;
  }

  function chips(host) {
    host.replaceChildren();
    const cats = data.categories.filter((c) => c.name !== "Cursos" || c.count > 0);
    const total = data.items.filter((i) => i.category !== "Cursos").length;
    const mk = (name, label, count) => h("button", { class: "chip", type: "button", "aria-pressed": String(state.cat === name),
      onclick: () => { state.cat = state.cat === name ? "" : name; state.shown = PAGE; syncUrl(); renderFeed(); if (host.id === "chips-hero") $("#achados").scrollIntoView(); } }, label, h("small", { text: String(count) }));
    host.append(mk("", "Todos", total), ...cats.map((c) => mk(c.name, c.name, c.count)));
    host.firstChild.onclick = () => { state.cat = ""; state.shown = PAGE; syncUrl(); renderFeed(); if (host.id === "chips-hero") $("#achados").scrollIntoView(); };
  }

  function renderFeed() {
    const list = filtered();
    const host = $("#cards");
    host.replaceChildren();
    chips($("#chips")); chips($("#chips-hero"));
    $$("[data-q]").forEach((i) => { if (i.value !== state.q) i.value = state.q; });
    const label = state.cat ? ` em ${state.cat}` : "";
    $("#achados-total").textContent = list.length ? `${list.length} ${list.length === 1 ? "achado" : "achados"}${label}${state.q ? ` para “${state.q}”` : ""}` : "";
    if (!data.items.length) {
      host.append(h("p", { class: "state" }, h("b", { text: "A vitrine está sendo montada. " }), "Volte em breve: os primeiros achados chegam logo."));
    } else if (!list.length) {
      host.append(h("p", { class: "state" }, h("b", { text: "Nada encontrado" }), state.q ? ` para “${state.q}”` : "", ". Tente outra palavra, outra categoria ou limpe os filtros.",
        " ", h("button", { class: "btn btn-soft btn-small", type: "button", onclick: clearFilters }, "Limpar filtros")));
    } else {
      list.slice(0, state.shown).forEach((it, i) => host.append(card(it, i)));
    }
    $("#mais").hidden = list.length <= state.shown;
    paintBag(false);
    observeReveals();
  }

  function clearFilters() { Object.assign(state, { q: "", cat: "", preco: "", ordem: "", shown: PAGE }); $("#f-preco").value = ""; $("#f-ordem").value = ""; syncUrl(); renderFeed(); }

  function syncUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.cat) p.set("c", state.cat);
    const qs = p.toString();
    history.replaceState(null, "", `${location.pathname}${qs ? `?${qs}` : ""}${location.hash}`);
  }

  // ---------------- seções ----------------
  function renderBoard() {
    const pool = data.items.filter((i) => i.image && i.category !== "Cursos");
    const pick = [...pool.filter((i) => i.highlight), ...pool.filter((i) => !i.highlight)].slice(0, 3);
    $("#board").replaceChildren(...pick.map((it) => h("button", { class: "pin-card", type: "button", "aria-label": `Ver detalhes: ${it.title}`, onclick: () => openProduct(it.id) },
      h("img", { src: safeUrl(it.image), alt: "", width: 300, height: 300, loading: "eager", referrerpolicy: "no-referrer" }), h("b", { text: it.title }), h("span", { text: money(it.price) || "Ver preço" }))));
  }

  function renderBand() {
    const deals = data.items.filter((i) => off(i) >= 5 && i.category !== "Cursos").sort((a, b) => off(b) - off(a)).slice(0, 10);
    const list = deals.length >= 3 ? deals : data.items.filter((i) => i.highlight && i.category !== "Cursos").slice(0, 10);
    const sec = $("#destaques");
    sec.hidden = list.length < 3;
    if (sec.hidden) return;
    $("#destaques-t").textContent = deals.length >= 3 ? "Ofertas em destaque" : "Achados em destaque";
    $("#destaques-sub").textContent = deals.length >= 3 ? "Preços abaixo do valor anterior que vimos no marketplace." : "Escolhidos para começar.";
    $("#trilho").replaceChildren(...list.map((it, i) => card(it, i)));
  }

  function renderCourses() {
    const list = data.items.filter((i) => i.category === "Cursos");
    $("#cursos").hidden = !list.length;
    $$("[data-courses]").forEach((a) => { a.hidden = !list.length; });
    if (list.length) $("#cards-cursos").replaceChildren(...list.map((it, i) => card(it, i)));
  }

  function renderSocials() {
    const entries = Object.entries(data.store.socials || {}).filter(([k, u]) => SOCIAL_LABELS[k] && safeUrl(u));
    $("#siga").hidden = !entries.length;
    const make = (cls) => entries.map(([k, u]) => h("a", { class: `btn btn-small${k === "youtube" && cls ? " yt" : ""}`, href: u, target: "_blank", rel: "noopener" }, SOCIAL_LABELS[k]));
    $("#redes").replaceChildren(...make(true));
    $("#redes-rodape").replaceChildren(...make(false));
  }

  // ---------------- detalhe ----------------
  function openProduct(id) {
    const it = byId.get(id);
    if (!it) return;
    const dlg = $("#produto");
    const pct = off(it);
    const price = money(it.price);
    const facts = [it.rating ? `Nota ${String(it.rating).replace(".", ",")}` : null, it.sold ? `${it.sold.toLocaleString("pt-BR")} vendidos` : null, it.price_date ? `preço visto em ${dayBR(it.price_date)}` : null].filter(Boolean).join(" · ");
    dlg.replaceChildren(
      h("button", { class: "close", type: "button", onclick: () => dlg.close() }, "Fechar"),
      h("div", { class: "sheet-body" },
        h("div", { class: "sheet-art" }, h("img", { src: safeUrl(it.image), alt: it.title, width: 600, height: 600, referrerpolicy: "no-referrer" })),
        h("div", { class: "sheet-info" },
          h("span", { class: "tag", text: `${it.category} · ${it.marketplace_name}` }),
          h("h2", { id: "produto-titulo", text: it.title }),
          it.blurb ? h("p", { text: it.blurb }) : null,
          h("div", { class: "price" }, h("b", { text: price || "Preço na página do marketplace" }), it.original_price && pct ? h("s", { text: money(it.original_price) }) : null,
            pct >= 5 ? h("span", { class: "off", style: "position:static", text: `-${pct}%` }) : null),
          facts ? h("p", { class: "small", text: facts }) : null,
          h("p", { class: "small", text: "O preço pode mudar: confira na página do marketplace antes de finalizar. Se você comprar pelo botão abaixo, o Mural recebe uma comissão, sem custo extra para você." }),
          h("div", { class: "sheet-actions" },
            h("a", { class: "btn btn-red", href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin" }, `Quero esse na ${it.marketplace_name}`),
            h("button", { class: "btn btn-soft", type: "button", "data-pin": it.id, "data-label": "1", onclick: () => togglePin(it.id) }, svg(PIN, 18), inBag(it.id) ? "Fixado no mural" : "Fixar no mural"),
            h("button", { class: "btn btn-soft", type: "button", onclick: () => share(it) }, svg(SHARE, 18), "Compartilhar")))));
    paintBag(false);
    if (!dlg.open) dlg.showModal();
    history.replaceState(null, "", `${location.pathname}${location.search}#${id}`);
  }

  // ---------------- Meu mural ----------------
  function renderBag() {
    const dlg = $("#sacola");
    const found = bag.map((id) => byId.get(id)).filter(Boolean);
    const gone = bag.filter((id) => !byId.has(id));
    const groups = new Map();
    found.forEach((it) => groups.set(it.marketplace_name, [...(groups.get(it.marketplace_name) || []), it]));
    const list = h("div", { class: "drawer-list" });
    if (!bag.length) list.append(h("p", { class: "empty-bag", text: "Seu mural está vazio. Toque no alfinete dos achados de que você gostar para fixá-los aqui." }));
    groups.forEach((items, name) => {
      const sum = items.reduce((s, i) => s + (i.price || 0), 0);
      list.append(h("section", { class: "group" }, h("h3", {}, name, h("span", { text: `${items.length} ${items.length === 1 ? "item" : "itens"}${sum ? ` · ${money(sum)}` : ""}` })),
        items.map((it) => h("div", { class: "row" },
          h("img", { src: safeUrl(it.image), alt: "", width: 64, height: 64, referrerpolicy: "no-referrer" }),
          h("div", {}, h("div", { class: "row-name", text: it.title }),
            h("div", { class: "row-sub" }, it.price ? h("span", { text: money(it.price) }) : null,
              h("a", { href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin" }, "Quero esse"),
              h("button", { class: "rm", type: "button", onclick: () => togglePin(it.id) }, "Tirar")))))));
    });
    gone.forEach((id) => list.append(h("div", { class: "row" }, h("div"), h("div", {}, h("div", { class: "row-name", text: "Achado que saiu do mural" }),
      h("div", { class: "row-sub" }, h("button", { class: "rm", type: "button", onclick: () => togglePin(id) }, "Tirar"))))));
    const parts = [
      h("div", { class: "drawer-head" }, h("h2", { id: "sacola-titulo", text: "Meu mural" }), h("button", { class: "close", type: "button", onclick: () => dlg.close() }, "Fechar")),
      h("p", { class: "drawer-note", text: "Sua lista de achados fixados. Ela fica só neste aparelho. Cada item abre no marketplace, onde você paga e acompanha a entrega." }),
      list];
    if (found.length) {
      const total = found.reduce((s, i) => s + (i.price || 0), 0);
      parts.push(h("div", { class: "drawer-foot" },
        h("p", { class: "total" }, total ? `Soma de referência: ${money(total)}` : "Achados fixados", h("small", { text: "Preços vistos aqui podem mudar no marketplace. Frete e descontos são calculados lá." })),
        h("div", { class: "btns" },
          h("button", { class: "btn btn-soft", type: "button", onclick: copyList }, "Copiar lista"),
          h("a", { class: "btn btn-ink", href: `https://wa.me/?text=${encodeURIComponent(listText(found))}`, target: "_blank", rel: "noopener" }, "Enviar no WhatsApp"))));
    }
    dlg.replaceChildren(...parts);
  }
  const listText = (items) => ["Meus achados no Mural na Web:", ...items.map((i) => `• ${i.title}${i.price ? ` (${money(i.price)})` : ""} — ${i.url}`)].join("\n");
  async function copyList() {
    try { await navigator.clipboard.writeText(listText(bag.map((id) => byId.get(id)).filter(Boolean))); toast("Lista copiada"); } catch { toast("Não consegui copiar"); }
  }
  function openBag() { renderBag(); const d = $("#sacola"); if (!d.open) d.showModal(); }

  // ---------------- entradas ----------------
  let io = null;
  function observeReveals() {
    const targets = $$(".rv:not(.in)");
    if (!("IntersectionObserver" in window) || reduced) { targets.forEach((t) => t.classList.add("in")); return; }
    io = io || new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -6% 0px", threshold: 0.04 });
    targets.forEach((t) => io.observe(t));
  }

  function wire() {
    $$("[data-search]").forEach((f) => f.addEventListener("submit", (e) => {
      e.preventDefault();
      state.q = $("[data-q]", f).value.trim(); state.shown = PAGE; syncUrl(); renderFeed(); $("#achados").scrollIntoView();
    }));
    $$("[data-q]").forEach((i) => i.addEventListener("input", () => { clearTimeout(wire.t); wire.t = setTimeout(() => { state.q = i.value.trim(); state.shown = PAGE; syncUrl(); renderFeed(); }, 220); }));
    $("#f-preco").addEventListener("change", (e) => { state.preco = e.target.value; state.shown = PAGE; renderFeed(); });
    $("#f-ordem").addEventListener("change", (e) => { state.ordem = e.target.value; state.shown = PAGE; renderFeed(); });
    $("#mais").addEventListener("click", () => { state.shown += PAGE; renderFeed(); });
    $$("[data-open-bag]").forEach((b) => b.addEventListener("click", openBag));
    $$("dialog").forEach((d) => {
      d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
      d.addEventListener("close", () => { if (location.hash.startsWith("#p")) history.replaceState(null, "", `${location.pathname}${location.search}`); });
    });
    $$(".hero .lead, .hero h1, .head, .steps li, .notice, .faq details, .follow-copy, .follow-img").forEach((el, i) => { el.classList.add("rv"); el.style.setProperty("--i", String(i % 4)); });
  }

  // ---------------- início ----------------
  async function start() {
    $("#ano").textContent = String(new Date().getFullYear());
    wire();
    const p = new URLSearchParams(location.search);
    state.q = (p.get("q") || "").slice(0, 80); state.cat = (p.get("c") || "").slice(0, 40);

    const loaded = await load();
    if (loaded && Array.isArray(loaded.items)) {
      data = {
        items: loaded.items.filter((i) => i && typeof i.id === "string" && safeUrl(i.url) && typeof i.title === "string" && safeUrl(i.image)),
        categories: Array.isArray(loaded.categories) ? loaded.categories : [],
        store: loaded.store || {},
      };
    }
    data.items.forEach((i) => byId.set(i.id, i));
    if (state.cat && !data.items.some((i) => i.category === state.cat)) state.cat = "";
    const s = data.store;
    if (s.tagline) $("#titulo").textContent = s.tagline;
    if (s.subtitle) $("#subtitulo").textContent = s.subtitle;
    if (s.disclosure) { $("#aviso").textContent = s.disclosure; $("#aviso-rodape").textContent = s.disclosure; }
    renderBoard(); renderBand(); renderCourses(); renderSocials(); renderFeed();
    paintBag(false); observeReveals();
    if (/^#p\d+$/.test(location.hash)) openProduct(location.hash.slice(1));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
