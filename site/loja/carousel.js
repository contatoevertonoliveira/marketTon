/* Carrossel de fotos do produto (vitrine e página do produto). Funciona sem JS (rolagem horizontal com encaixe); o script só acrescenta
   setas, bolinhas, teclado e a contagem. Nada é carregado de terceiros além das próprias fotos. */
(function () {
  "use strict";
  function mk(tag, cls, text, attrs) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text) el.textContent = text;
    for (var k in attrs || {}) el.setAttribute(k, attrs[k]);
    return el;
  }
  function enhance(root) {
    if (!root || root.getAttribute("data-ready")) return;
    var track = root.querySelector(".car-track");
    if (!track || track.children.length < 2) return;
    root.setAttribute("data-ready", "1");
    var n = track.children.length;
    var prev = mk("button", "car-btn car-prev", "‹", { type: "button", "aria-label": "Foto anterior" });
    var next = mk("button", "car-btn car-next", "›", { type: "button", "aria-label": "Próxima foto" });
    var dots = mk("div", "car-dots", "", { role: "tablist" });
    var dotEls = [];
    for (var i = 0; i < n; i++) {
      (function (i) {
        var d = mk("button", "car-dot", "", { type: "button", "aria-label": "Foto " + (i + 1) + " de " + n });
        d.addEventListener("click", function () { go(i); });
        dots.appendChild(d);
        dotEls.push(d);
      })(i);
    }
    function index() { return Math.max(0, Math.min(n - 1, Math.round(track.scrollLeft / Math.max(1, track.clientWidth)))); }
    function go(i) { track.scrollTo({ left: ((i + n) % n) * track.clientWidth, behavior: "smooth" }); }
    var raf = 0;
    function paint() {
      raf = 0;
      var cur = index();
      for (var j = 0; j < n; j++) dotEls[j].setAttribute("aria-current", j === cur ? "true" : "false");
    }
    track.addEventListener("scroll", function () { if (!raf) raf = requestAnimationFrame(paint); }, { passive: true });
    prev.addEventListener("click", function () { go(index() - 1); });
    next.addEventListener("click", function () { go(index() + 1); });
    root.setAttribute("tabindex", "0");
    root.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { go(index() - 1); e.preventDefault(); }
      else if (e.key === "ArrowRight") { go(index() + 1); e.preventDefault(); }
    });
    root.appendChild(prev);
    root.appendChild(next);
    root.appendChild(dots);
    paint();
  }
  window.muralCarousel = enhance;
  function all() { var l = document.querySelectorAll(".car"); for (var i = 0; i < l.length; i++) enhance(l[i]); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", all); else all();
})();
