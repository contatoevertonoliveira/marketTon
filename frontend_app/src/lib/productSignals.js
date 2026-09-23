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

export function sellerLocation(product) {
  const city = product.attributes?.seller_city;
  const state = product.attributes?.seller_state;
  if (city && state) return `${city}, ${state}`;
  return state || city || null;
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
