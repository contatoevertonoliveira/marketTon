// Sinais reais de confiabilidade/demanda por produto, usados tanto para
// ordenar o grid de cards quanto para os selos exibidos neles. Nada aqui é
// estimado — só reorganiza dado que a própria API do marketplace devolveu.

// Mercado Envios Full (estoque no armazém da ML) entrega mais rápido e
// previsível que despacho direto do vendedor. `cross_docking`/`xd_drop_off`
// ficam no meio: a ML recolhe no vendedor mas não estoca.
const LOGISTIC_SPEED_RANK = {
  fulfillment: 3,
  cross_docking: 2,
  xd_drop_off: 2,
  drop_off: 1,
  me1: 1,
};

export function logisticSpeedRank(product) {
  const type = product.attributes?.shipping_logistic_type;
  return type ? LOGISTIC_SPEED_RANK[type] ?? 0 : 0;
}

// "none" = despacha do Brasil. Qualquer outro valor (ou o campo ausente para
// marketplaces que não o expõem) não é tratado como nacional — na dúvida,
// não afirma.
export function shipsFromBrazil(product) {
  const mode = product.attributes?.international_delivery_mode;
  return mode === "none";
}

// Comparação de preço com outras ofertas. Duas fontes possíveis, e a UI
// precisa saber qual é qual — não são a mesma garantia:
// - `confirmed`: Mercado Livre expõe um ID de catálogo compartilhado entre
//   vendedores, então "outras ofertas" é o mesmo item, com certeza.
// - `!confirmed` (Shopee): a Affiliate Open API não tem esse ID; o que dá
//   pra comparar são outras ofertas que apareceram na mesma busca por
//   palavra-chave — aproxima concorrência de nicho, não confirma item igual.
export function priceCompetitiveness(product) {
  const confirmedOffers = product.attributes?.competing_offers;
  if (confirmedOffers) {
    const min = product.attributes.competing_price_min;
    const isLowest = product.price != null && min != null && product.price <= min + 0.01;
    return {
      offers: confirmedOffers,
      min,
      max: product.attributes.competing_price_max,
      isLowest,
      confirmed: true,
    };
  }
  const similarOffers = product.attributes?.similar_offers;
  if (similarOffers) {
    const min = product.attributes.similar_price_min;
    const isLowest = product.price != null && min != null && product.price <= min + 0.01;
    return {
      offers: similarOffers,
      min,
      max: product.attributes.similar_price_max,
      isLowest,
      confirmed: false,
    };
  }
  return null;
}

export function sellerLocation(product) {
  const city = product.attributes?.seller_city;
  const state = product.attributes?.seller_state;
  if (city && state) return `${city}, ${state}`;
  return state || city || null;
}

const GOOD_REPUTATION_LEVELS = new Set(["5_green", "4_light_green"]);

// Selo "Aprovado": não é a camada de IA do sistema (ela está desligada — exige
// chave de API que ainda não foi configurada em Integrações). É uma regra
// determinística sobre os mesmos sinais reais já coletados — demanda, vendedor
// confiável, preço competitivo, comissão conhecida — com o motivo auditável,
// igual à explicação que os scores já mostram. Passa quem atende pelo menos 3
// dos 4 critérios: um produto sem nenhum sinal negativo não deveria precisar
// de todos os 4 pra ser aprovado, mas dois ou menos não é indicação séria.
export function approvalVerdict(product) {
  const checks = [
    {
      label: "demanda real",
      pass:
        (product.sold_quantity != null && product.sold_quantity > 0) ||
        (product.ranking_position != null && product.ranking_position <= 10),
    },
    {
      label: "vendedor confiável",
      pass:
        product.seller_is_official_store === true ||
        GOOD_REPUTATION_LEVELS.has(product.seller_reputation_level) ||
        (product.rating != null && product.rating >= 4.5),
    },
    {
      label: "preço competitivo",
      pass: priceCompetitiveness(product)?.isLowest === true,
    },
    {
      label: "comissão conhecida",
      pass: product.affiliate_commission_pct != null,
    },
  ];
  const passed = checks.filter((c) => c.pass).map((c) => c.label);
  const failed = checks.filter((c) => !c.pass).map((c) => c.label);
  return { approved: passed.length >= 3, passed, failed };
}

// Prioriza, nessa ordem: vendas reais -> avaliação -> velocidade de entrega
// -> posição no ranking de mais vendidos (fallback quando o marketplace não
// expõe vendas, caso da Mercado Livre hoje) -> score de Oportunidade.
// Produtos sem nenhum sinal de demanda afundam para o fim, não para o meio.
export function demandComparator(a, b) {
  const sold = (b.sold_quantity ?? -1) - (a.sold_quantity ?? -1);
  if (sold !== 0) return sold;

  const rating = (b.rating ?? -1) - (a.rating ?? -1);
  if (rating !== 0) return rating;

  const logistics = logisticSpeedRank(b) - logisticSpeedRank(a);
  if (logistics !== 0) return logistics;

  const aRank = a.ranking_position ?? Infinity;
  const bRank = b.ranking_position ?? Infinity;
  if (aRank !== bRank) return aRank - bRank;

  return (b.scores?.OPPORTUNITY ?? -1) - (a.scores?.OPPORTUNITY ?? -1);
}

// Concorrência entre afiliados. A Affiliate Open API da Shopee não expõe esse
// número — ele é digitado pelo usuário (lido no Centro de Afiliados), então
// só classifica quando existe. Os cortes são heurísticos, ajustáveis aqui.
export function competitionLevel(product) {
  const n = product.affiliate_count;
  if (n == null) return null;
  if (n <= 50) return { level: "low", label: "baixa concorrência", color: "#1a7a54", bg: "#e5faf1" };
  if (n <= 300) return { level: "medium", label: "concorrência média", color: "#b8720a", bg: "#fff4e5" };
  return { level: "high", label: "muita concorrência", color: "#c31e3f", bg: "#fef1f4" };
}

// "Oportunidade de live": boa comissão + poucos afiliados.
export function isLiveOpportunity(product) {
  return (
    competitionLevel(product)?.level === "low" &&
    product.affiliate_commission_pct != null &&
    product.affiliate_commission_pct >= 8
  );
}

const STOPWORDS = new Set([
  "de", "da", "do", "das", "dos", "para", "com", "sem", "em", "e", "ou", "a", "o", "as", "os", "um", "uma",
  "kit", "novo", "nova", "original", "premium", "promoção", "oferta", "unidade", "unidades", "pcs", "cm", "ml",
]);

function slug(word) {
  return word
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]/g, "");
}

// Hashtags sugeridas por regra: palavras-chave do título + tags fixas de
// vídeo/afiliado da Shopee. NÃO são medidas por visualização — a Shopee não
// publica volume de hashtag por API, então a UI não pode afirmar popularidade.
export function suggestHashtags(product, limit = 12) {
  const words = (product.title || "")
    .split(/[\s,.\-/|()+]+/)
    .map(slug)
    .filter((w) => w.length >= 4 && !STOPWORDS.has(w) && !/^\d+$/.test(w));
  const unique = [...new Set(words)].slice(0, 5);
  const bigram = unique.length >= 2 ? [unique[0] + unique[1]] : [];
  const fixed = ["shopeevideo", "achadinhosshopee", "shopeefinds", "shopeebrasil", "comprinhasshopee", "fyp"];
  const brand = product.brand ? [slug(product.brand)].filter(Boolean) : [];
  return [...new Set([...unique, ...bigram, ...brand, ...fixed])].slice(0, limit).map((t) => `#${t}`);
}

// Ordena para achar nicho de baixa concorrência: quem tem nº de afiliados
// conhecido vem primeiro (menos afiliados, depois maior comissão); os sem
// dado seguem a ordem de demanda.
export function opportunityComparator(a, b) {
  const an = a.affiliate_count;
  const bn = b.affiliate_count;
  if (an != null && bn == null) return -1;
  if (an == null && bn != null) return 1;
  if (an != null && bn != null && an !== bn) return an - bn;
  if (an != null && bn != null) {
    const c = (b.affiliate_commission_pct ?? -1) - (a.affiliate_commission_pct ?? -1);
    if (c !== 0) return c;
  }
  return demandComparator(a, b);
}

export const AFFILIATE_PERIODS = { total: "no total", semana: "na semana", mes: "no mês" };

// Estoque digitado (a API da Shopee não expõe). Corte heurístico: abaixo de
// 100 unidades a oferta pode acabar antes de valer o esforço de um vídeo.
export function stockLevel(product) {
  const n = product.manual_stock;
  if (n == null) return null;
  if (n < 100) return { label: "estoque baixo", color: "#c31e3f", bg: "#fef1f4" };
  if (n < 1000) return { label: "estoque médio", color: "#b8720a", bg: "#fff4e5" };
  return { label: "estoque alto", color: "#1a7a54", bg: "#e5faf1" };
}
