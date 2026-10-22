// Achados do Felix — vitrine pública. Sem dependências, sem cookies, sem rastreadores.
// Os dados vêm de /api/loja/catalogo (publicado pelo marketTon). A sacola fica só neste aparelho (localStorage).
(() => {
  "use strict";

  const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const FIELDS = ["var(--red)", "var(--mustard)", "var(--slate)", "var(--maroon)"];
  const BAG_KEY = "achados:sacola";
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  const safeUrl = (u) => (typeof u === "string" && u.startsWith("https://") ? u : "");
  const money = (v) => (v == null ? null : BRL.format(v));
  const dayBR = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  const field = (i) => FIELDS[i % FIELDS.length];

  // ---------------- sacola ----------------
  let bag = [];
  try { bag = JSON.parse(localStorage.getItem(BAG_KEY) || "[]").filter((x) => typeof x === "string"); } catch { bag = []; }
  const saveBag = () => { try { localStorage.setItem(BAG_KEY, JSON.stringify(bag)); } catch { /* sem armazenamento: segue em memória */ } };
  const inBag = (id) => bag.includes(id);

  function paintCount(bump) {
    $$("[data-bag-count]").forEach((el) => {
      el.textContent = String(bag.length);
      if (bump && !reduced) { el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); }
    });
    $$("[data-bag-id]").forEach((btn) => {
      const on = inBag(btn.dataset.bagId);
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "Na sacola" : "Guardar";
    });
  }

  function toggleBag(id) {
    bag = inBag(id) ? bag.filter((x) => x !== id) : [...bag, id];
    saveBag();
    paintCount(true);
    if ($("#sacola").open) renderBag();
  }

  // ---------------- dados ----------------
  let data = { items: [], categories: [], store: {} };
  const byId = new Map();

  async function load() {
    try {
      const r = await fetch("/api/loja/catalogo", { cache: "no-cache" });
      if (r.ok) return await r.json();
    } catch { /* sem rede */ }
    return null;
  }

  // ---------------- abertura: a parede ----------------
  function buildWall(items) {
    const wall = $("#wall");
    wall.replaceChildren();
    const t = parseFloat(getComputedStyle(wall).getPropertyValue("--t")) || 110;
    const tile = wall.getBoundingClientRect();
    const px = (() => { const probe = h("div", { style: "width:var(--t);position:absolute;visibility:hidden" }); wall.append(probe); const w = probe.getBoundingClientRect().width; probe.remove(); return w || t; })();
    const cols = Math.ceil(window.innerWidth / (px + 8)) + 2;
    const rows = Math.ceil((tile.height || window.innerHeight) / (px + 8)) + 1;
    const withPhoto = items.filter((i) => i.image);
    let n = 0, p = 0;
    for (let r = 0; r < rows; r++) {
      const row = h("div", { class: "wall-row" });
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const cell = h("div", { class: "wall-tile", style: `--c:${field(idx + r)};--d:${(r + c) * 55}` });
        // Um achado a cada três campos; o resto da parede são campos de cor, como etiquetas vazias.
        if (withPhoto.length && (c + r * 2) % 3 === 0) {
          const it = withPhoto[p++ % withPhoto.length];
          cell.append(h("img", { src: safeUrl(it.image), alt: "", width: 120, height: 120, loading: r < 3 ? "eager" : "lazy", decoding: "async", referrerpolicy: "no-referrer" }));
        }
        row.append(cell);
        n++;
      }
      wall.append(row);
    }
  }

  // ---------------- catálogo ----------------
  function tileEl(it, i) {
    const art = h("button", { class: "tile-art", type: "button", style: `--c:${field(i)}`, "aria-label": `Ver detalhes: ${it.title}`, onclick: () => openProduct(it.id) },
      h("img", { src: safeUrl(it.image), alt: it.title, width: 400, height: 400, loading: i < 8 ? "eager" : "lazy", decoding: "async", referrerpolicy: "no-referrer" }));
    const price = money(it.price);
    const fact = h("p", { class: "tile-fact" },
      it.original_price ? h("s", { text: money(it.original_price) }) : null,
      price ? `${price} · ${it.marketplace_name}` : `Ver preço · ${it.marketplace_name}`);
    const actions = h("div", { class: "tile-actions" },
      h("button", { class: "btn btn-ghost", type: "button", "data-bag-id": it.id, "aria-pressed": String(inBag(it.id)), onclick: () => toggleBag(it.id) }, inBag(it.id) ? "Na sacola" : "Guardar"),
      h("a", { class: "go", href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin", "aria-label": `Comprar ${it.title} na ${it.marketplace_name}` }, `${it.marketplace_name} ↗`));
    return h("article", { class: `tile rv${it.highlight ? " big" : ""}`, "data-id": it.id },
      art, h("div", { class: "tile-meta" }, h("h4", { class: "tile-name", text: it.title }), fact, actions));
  }

  function buildCatalogue() {
    const host = $("#categorias");
    const nav = $("#indice");
    host.replaceChildren();
    nav.replaceChildren();
    const items = data.items;
    if (!items.length) {
      host.append(h("p", { class: "state", text: "A vitrine está sendo montada. Volte em breve: os primeiros achados chegam logo." }));
      $("#catalogo-total").textContent = "";
      nav.hidden = true;
      return;
    }
    $("#catalogo-total").textContent = `${items.length} ${items.length === 1 ? "achado" : "achados"}, de ${new Set(items.map((i) => i.marketplace_name)).size > 1 ? "mais de um marketplace" : items[0].marketplace_name}`;
    let order = 0;
    const cats = data.categories.length ? data.categories.map((c) => c.name) : [...new Set(items.map((i) => i.category))];
    cats.forEach((name, ci) => {
      const list = items.filter((i) => i.category === name);
      if (!list.length) return;
      const id = `cat-${ci}`;
      nav.append(h("a", { href: `#${id}`, "data-cat": name }, name, h("span", { text: String(list.length) })));
      const grid = h("div", { class: "grid" });
      list.forEach((it) => grid.append(tileEl(it, order++)));
      host.append(h("section", { class: "cat", id, "aria-labelledby": `${id}-t` },
        h("div", { class: "cat-head rv" }, h("h3", { id: `${id}-t`, text: name }), h("p", { text: `${list.length} ${list.length === 1 ? "achado" : "achados"}` })),
        h("div", { class: "grid-wrap" }, grid)));
    });
    $$(".tile", host).forEach((el, i) => el.style.setProperty("--i", String(i % 6)));
    wirePreview(nav);
    observeReveals();
  }

  // ---------------- prévia ao apontar a categoria ----------------
  function wirePreview(nav) {
    const box = $("#previa");
    const img = $("img", box);
    const show = (a) => {
      const it = data.items.find((i) => i.category === a.dataset.cat && i.image);
      if (!it) return;
      img.src = safeUrl(it.image);
      box.style.setProperty("--c", field(data.items.indexOf(it)));
      box.classList.add("on");
    };
    $$("a", nav).forEach((a) => {
      a.addEventListener("pointerenter", () => show(a));
      a.addEventListener("focus", () => show(a));
      a.addEventListener("pointerleave", () => box.classList.remove("on"));
      a.addEventListener("blur", () => box.classList.remove("on"));
    });
    // categoria em foco enquanto a página rola
    if ("IntersectionObserver" in window) {
      const links = new Map($$("a", nav).map((a) => [a.getAttribute("href").slice(1), a]));
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { links.forEach((l) => l.classList.remove("on")); links.get(e.target.id)?.classList.add("on"); } });
      }, { rootMargin: "-30% 0px -60% 0px" });
      $$(".cat").forEach((c) => io.observe(c));
    }
  }

  // ---------------- detalhe ----------------
  const productDlg = () => $("#produto");

  function openProduct(id) {
    const it = byId.get(id);
    if (!it) return;
    const dlg = productDlg();
    const idx = data.items.indexOf(it);
    const price = money(it.price);
    dlg.replaceChildren(
      h("button", { class: "sheet-close", type: "button", onclick: () => dlg.close(), "aria-label": "Fechar detalhes" }, "Fechar"),
      h("div", { class: "sheet-body" },
        h("div", { class: "sheet-art", style: `--c:${field(idx)}` }, h("img", { src: safeUrl(it.image), alt: it.title, width: 600, height: 600, referrerpolicy: "no-referrer" })),
        h("div", { class: "sheet-info" },
          h("p", { class: "where", text: `${it.category} · achado na ${it.marketplace_name}` }),
          h("h2", { id: "produto-titulo", text: it.title }),
          it.blurb ? h("p", { text: it.blurb }) : null,
          price ? h("p", { class: "price" }, it.original_price ? h("s", { text: money(it.original_price) }) : null, price) : h("p", { class: "price", text: "Preço na página do marketplace" }),
          h("p", { class: "small" },
            [it.rating ? `Nota ${String(it.rating).replace(".", ",")}` : null, it.sold ? `${it.sold.toLocaleString("pt-BR")} vendidos` : null, it.price_date ? `preço visto em ${dayBR(it.price_date)}` : null].filter(Boolean).join(" · ")),
          h("p", { class: "small", text: "O preço pode mudar: confira na página do marketplace antes de finalizar. Se você comprar pelo botão abaixo, recebemos uma comissão, sem custo extra para você." }),
          h("div", { class: "sheet-actions" },
            h("a", { class: "btn", href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin" }, `Comprar na ${it.marketplace_name} ↗`),
            h("button", { class: "btn btn-ghost", type: "button", "data-bag-id": it.id, "aria-pressed": String(inBag(it.id)), onclick: () => toggleBag(it.id) }, inBag(it.id) ? "Na sacola" : "Guardar")))));
    paintCount(false);
    if (!dlg.open) dlg.showModal();
  }

  // ---------------- sacola ----------------
  function renderBag() {
    const dlg = $("#sacola");
    const found = bag.map((id) => byId.get(id)).filter(Boolean);
    const gone = bag.filter((id) => !byId.has(id));
    const groups = new Map();
    found.forEach((it) => groups.set(it.marketplace_name, [...(groups.get(it.marketplace_name) || []), it]));

    const head = h("div", { class: "drawer-head" }, h("h2", { id: "sacola-titulo", text: "Sua sacola" }),
      h("button", { class: "drawer-close", type: "button", onclick: () => dlg.close() }, "Fechar"));
    const note = h("p", { class: "drawer-note", text: "A sacola é só uma lista para você não perder os achados. Cada item abre no marketplace, onde você paga e acompanha a entrega." });
    const list = h("div", { class: "drawer-list" });
    if (!bag.length) list.append(h("p", { class: "empty-bag", text: "Nada por aqui ainda. Toque em Guardar nos achados de que você gostar." }));
    groups.forEach((items, name) => {
      const sum = items.reduce((s, i) => s + (i.price || 0), 0);
      list.append(h("section", { class: "drawer-group" },
        h("h3", {}, name, h("span", { text: `${items.length} ${items.length === 1 ? "item" : "itens"}${sum ? ` · ${money(sum)}` : ""}` })),
        items.map((it) => h("div", { class: "row" },
          h("div", { class: "row-art", style: `--c:${field(data.items.indexOf(it))}` }, h("img", { src: safeUrl(it.image), alt: "", width: 64, height: 64, referrerpolicy: "no-referrer" })),
          h("div", {},
            h("div", { class: "row-name", text: it.title }),
            h("div", { class: "row-sub" },
              it.price ? h("span", { text: money(it.price) }) : null,
              h("a", { href: safeUrl(it.url), target: "_blank", rel: "sponsored noopener", referrerpolicy: "origin" }, `Comprar ↗`),
              h("button", { class: "rm", type: "button", onclick: () => toggleBag(it.id) }, "Tirar")))))));
    });
    if (gone.length) {
      list.append(h("section", { class: "drawer-group" }, h("h3", { text: "Não estão mais na vitrine" }),
        gone.map((id) => h("div", { class: "row gone" }, h("div", { class: "row-art" }), h("div", {}, h("div", { class: "row-name", text: "Achado que saiu da vitrine" }),
          h("div", { class: "row-sub" }, h("button", { class: "rm", type: "button", onclick: () => toggleBag(id) }, "Tirar")))))));
    }
    const foot = h("div", { class: "drawer-foot" });
    if (found.length) {
      const total = found.reduce((s, i) => s + (i.price || 0), 0);
      foot.append(
        h("p", { class: "total" }, total ? `Soma de referência: ${money(total)}` : "Itens guardados", h("small", { text: "Os preços são os vistos na vitrine e podem mudar no marketplace. Frete e descontos são calculados lá." })),
        h("div", { class: "acts" },
          h("button", { class: "btn btn-ghost", type: "button", onclick: copyList }, "Copiar minha lista"),
          h("a", { class: "btn", href: whatsappHref(found), target: "_blank", rel: "noopener" }, "Enviar no WhatsApp")));
    }
    dlg.replaceChildren(head, note, list, ...(found.length ? [foot] : []));
  }

  function listText(items) {
    return ["Meus achados:", ...items.map((i) => `• ${i.title}${i.price ? ` (${money(i.price)})` : ""} — ${i.url}`)].join("\n");
  }
  const whatsappHref = (items) => `https://wa.me/?text=${encodeURIComponent(listText(items))}`;
  async function copyList(e) {
    const items = bag.map((id) => byId.get(id)).filter(Boolean);
    const btn = e.currentTarget;
    try { await navigator.clipboard.writeText(listText(items)); btn.textContent = "Lista copiada"; } catch { btn.textContent = "Não consegui copiar"; }
    setTimeout(() => { btn.textContent = "Copiar minha lista"; }, 1800);
  }

  function openBag() {
    renderBag();
    const dlg = $("#sacola");
    if (!dlg.open) dlg.showModal();
  }

  // ---------------- "como funciona", rodapé e entradas ----------------
  function fillStages() {
    const withPhoto = data.items.filter((i) => i.image);
    $$("[data-stage]").forEach((img, i) => {
      const it = withPhoto[0];
      if (!it) { img.closest(".stage-art")?.setAttribute("hidden", ""); return; }
      img.src = safeUrl(it.image);
      img.alt = i === 0 ? it.title : "";
      img.referrerPolicy = "no-referrer";
    });
  }

  function buildMark() {
    const letters = "ACHADOS".split("");
    const heights = [78, 100, 64, 90, 72, 100, 84];
    const colours = [["var(--mustard)", "var(--mustard-ink)"], ["var(--ink)", "var(--bg)"], ["var(--bg)", "var(--ink)"], ["var(--maroon)", "var(--maroon-ink)"],
      ["var(--slate)", "var(--slate-ink)"], ["var(--mustard)", "var(--mustard-ink)"], ["var(--ink)", "var(--bg)"]];
    $("#marca").replaceChildren(...letters.map((l, i) => h("span", { "aria-hidden": "true", style: `--h:${heights[i]}%;--c:${colours[i][0]};--ci:${colours[i][1]}`, text: l })));
  }

  let io = null;
  function observeReveals() {
    const targets = $$(".rv:not(.in)");
    if (!("IntersectionObserver" in window) || reduced) { targets.forEach((t) => t.classList.add("in")); return; }
    io = io || new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    targets.forEach((t) => io.observe(t));
  }

  function watchBar() {
    const bar = $("#bar");
    const hero = $(".hero");
    const update = () => bar.classList.toggle("on", hero.getBoundingClientRect().bottom < 120);
    update();
    addEventListener("scroll", update, { passive: true });
    addEventListener("resize", update);
  }

  function dialogs() {
    for (const dlg of $$("dialog")) {
      dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); }); // clique no fundo fecha
    }
    $$("[data-open-bag]").forEach((b) => b.addEventListener("click", openBag));
  }

  // ---------------- início ----------------
  async function start() {
    $("#ano").textContent = String(new Date().getFullYear());
    buildMark();
    watchBar();
    dialogs();
    paintCount(false);
    $$("main > section > .wrap > h2, .stage, .faq-list details, .foot-body").forEach((el, i) => { el.classList.add("rv"); el.style.setProperty("--i", String(i % 4)); });

    const loaded = await load();
    if (loaded && Array.isArray(loaded.items)) {
      data = {
        items: loaded.items.filter((i) => i && typeof i.id === "string" && safeUrl(i.url) && typeof i.title === "string"),
        categories: Array.isArray(loaded.categories) ? loaded.categories : [],
        store: loaded.store || {},
      };
    }
    data.items.forEach((i) => byId.set(i.id, i));
    if (data.store.disclosure) $("#aviso-afiliado").textContent = data.store.disclosure;
    buildWall(data.items);
    buildCatalogue();
    fillStages();
    paintCount(false);
    observeReveals();
    let t;
    addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => buildWall(data.items), 250); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
