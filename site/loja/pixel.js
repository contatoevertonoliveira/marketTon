/* Pixel da Meta do Mural na Web, só depois do "Aceitar".
 * - Sem aceite (ou com "Recusar") nada da Meta é carregado: o site funciona igual.
 * - Eventos: PageView (toda página), ViewContent (página do produto) e OfferClick (clique em "Quero esse").
 * - Nada de dado pessoal é enviado por nós: só a página vista, o produto e o valor. A escolha fica no aparelho (localStorage).
 */
(function () {
  "use strict";
  var PIXEL_ID = "968058256367091";
  var KEY = "mural_consent";

  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function save(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* sem armazenamento: pergunta de novo na próxima visita */ } }

  function loadPixel() {
    if (window.fbq) return;
    var n = (window.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); });
    if (!window._fbq) window._fbq = n;
    n.push = n; n.loaded = true; n.version = "2.0"; n.queue = [];
    var s = document.createElement("script");
    s.async = true; s.src = "https://connect.facebook.net/en_US/fbevents.js";
    document.head.appendChild(s);
    window.fbq("init", PIXEL_ID);
    window.fbq("track", "PageView");
    var type = document.querySelector('meta[property="og:type"]');
    if (type && type.content === "product") {
      var title = document.querySelector('meta[property="og:title"]');
      var price = document.querySelector('meta[property="product:price:amount"]');
      window.fbq("track", "ViewContent", {
        content_name: title ? title.content : document.title,
        content_type: "product",
        value: price ? Number(price.content) : undefined,
        currency: "BRL"
      });
    }
    document.addEventListener("click", function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a.btn-red[href]") : null;
      if (a && window.fbq) window.fbq("trackCustom", "OfferClick", { content_name: document.title });
    }, true);
  }

  function banner() {
    var box = document.createElement("div");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Medição dos anúncios");
    box.style.cssText = "position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;max-width:560px;margin:0 auto;background:#fff;color:#171923;" +
      "border:1px solid #e3e6ee;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.18);padding:14px 16px;font:14px/1.45 Inter,system-ui,sans-serif";
    box.innerHTML = '<p style="margin:0 0 10px">Usamos o Pixel da Meta, <strong>só se você aceitar</strong>, para medir quais anúncios trazem visitas. ' +
      'Sem ele, o site funciona igual. <a href="https://felixsystems.com.br/privacidade.html" style="color:#A71920">Saiba mais</a>.</p>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end"></div>';
    var row = box.lastChild;
    function btn(label, bg, fg, border, value) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.style.cssText = "cursor:pointer;border-radius:999px;padding:8px 18px;font:600 13px Inter,system-ui,sans-serif;background:" + bg + ";color:" + fg + ";border:1px solid " + border;
      b.addEventListener("click", function () {
        save(value);
        box.remove();
        if (value === "yes") loadPixel();
      });
      return b;
    }
    row.appendChild(btn("Recusar", "#fff", "#171923", "#c9ced9", "no"));
    row.appendChild(btn("Aceitar", "#A71920", "#fff", "#A71920", "yes"));
    document.body.appendChild(box);
  }

  function start() {
    var v = read();
    if (v === "yes") loadPixel();
    else if (v !== "no") banner();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
