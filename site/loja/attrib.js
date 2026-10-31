/* Atribuição dos anúncios: a página do produto recebe ?utm_campaign=... do anúncio; este script repassa o nome da campanha ao link do botão de
 * compra (/r/<código>?c=...), para o contador de cliques saber de qual anúncio veio cada clique na oferta. Não guarda nada no aparelho e não envia
 * dado pessoal: só o nome da campanha que já está no endereço.
 */
(function () {
  "use strict";
  try {
    var q = new URLSearchParams(location.search);
    var c = String(q.get("utm_campaign") || "").toLowerCase().replace(/[^a-z0-9._-]/g, "").slice(0, 48);
    if (!c) return;
    var links = document.querySelectorAll('a[href*="/r/"]');
    for (var i = 0; i < links.length; i++) {
      try {
        var u = new URL(links[i].href, location.href);
        u.searchParams.set("c", c);
        links[i].href = u.toString();
      } catch (e) { /* link estranho: deixa como está */ }
    }
  } catch (e) { /* sem atribuição, o link funciona igual */ }
})();
