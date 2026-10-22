import React, { useEffect, useState } from "react";
import { getJSON, postJSON, putJSON } from "../lib/apiClient";
import ProductDetailDrawer from "./ProductDetail";
import { approvalVerdict, AFFILIATE_PERIODS, competitionLevel, isLiveOpportunity, stockLevel, suggestHashtags, logisticSpeedRank, priceCompetitiveness, sellerLocation, shipsFromBrazil } from "../lib/productSignals";

function fmtMoney(v, currency) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { style: "currency", currency: currency || "BRL" });
}

// O veredito não vem de IA (a camada de IA do sistema está desligada — falta
// configurar uma chave de API em Integrações). É uma regra determinística
// sobre os mesmos sinais reais mostrados no resto desta modal, com o motivo
// sempre visível — nada aqui é opaco.
function ApprovalBadge({ product }) {
  const verdict = approvalVerdict(product);
  return (
    <div
      style={{
        display: "inline-block",
        marginBottom: 8,
        padding: "4px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        background: verdict.approved ? "#2dce89" : "#f6f9fc",
        color: verdict.approved ? "#fff" : "#8898aa",
      }}
      title={
        verdict.approved
          ? `Passou: ${verdict.passed.join(", ")}`
          : `Passou: ${verdict.passed.join(", ") || "nenhum critério"} · Falta: ${verdict.failed.join(", ")}`
      }
    >
      {verdict.approved ? "✓ Aprovado pelo sistema" : `${verdict.passed.length}/4 critérios — ainda não aprovado`}
    </div>
  );
}

// ID numérico do item na Shopee (`itemId`): é o que se cola na busca do portal
// de afiliados ou na URL /offer/product_offer/<id> para achar o produto.
function ProductIdRow({ product }) {
  const [copied, setCopied] = useState("");
  const isShopee = product.marketplace === "shopee";

  function copy(key, text) {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(""), 1500);
    });
  }

  const btn = { padding: "2px 8px", fontSize: 11, borderRadius: 6, border: "1px solid #dde3ec", background: "#fff", cursor: "pointer" };
  return (
    <div style={{ fontSize: 12, color: "#525f7f", marginBottom: 8, display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <span>
        ID: <b style={{ userSelect: "all" }}>{product.external_id}</b>
      </span>
      <button style={btn} onClick={() => copy("id", product.external_id)}>{copied === "id" ? "Copiado ✓" : "Copiar ID"}</button>
      {product.affiliate_url && (
        <button style={btn} onClick={() => copy("aff", product.affiliate_url)}>{copied === "aff" ? "Copiado ✓" : "Copiar link afiliado"}</button>
      )}
      {isShopee && (
        <a href={`https://affiliate.shopee.com.br/offer/product_offer/${product.external_id}`} target="_blank" rel="noreferrer" style={{ color: "#5e72e4" }}>
          abrir no portal de afiliados ↗
        </a>
      )}
    </div>
  );
}

function CompetitionAndHashtags({ product }) {
  const [count, setCount] = useState(product.affiliate_count ?? "");
  const [period, setPeriod] = useState(product.affiliate_count_period || "total");
  const [stock, setStock] = useState(product.manual_stock ?? "");
  const [saved, setSaved] = useState({
    affiliate_count: product.affiliate_count,
    manual_stock: product.manual_stock,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const level = competitionLevel(saved);
  const stockInfo = stockLevel(saved);
  const tags = suggestHashtags(product);
  const small = { width: 84, padding: "3px 6px", border: "1px solid #dde3ec", borderRadius: 6, fontSize: 12 };

  async function save() {
    setSaving(true);
    setErr("");
    try {
      const toInt = (v) => (v === "" ? null : Math.max(0, parseInt(v, 10)));
      const updated = await putJSON(`/catalog/products/${product.id}/manual-signals`, {
        affiliate_count: toInt(count),
        affiliate_count_period: toInt(count) == null ? null : period,
        manual_stock: toInt(stock),
      });
      Object.assign(product, {
        affiliate_count: updated.affiliate_count,
        affiliate_count_period: updated.affiliate_count_period,
        manual_stock: updated.manual_stock,
      });
      setSaved({ affiliate_count: updated.affiliate_count, manual_stock: updated.manual_stock });
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  function copyTags() {
    navigator.clipboard?.writeText(tags.join(" ")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div style={{ marginTop: 10, fontSize: 12, borderTop: "1px solid #eef0f5", paddingTop: 10 }}>
      <div style={{ color: "#525f7f", marginBottom: 4, fontWeight: 600 }}>Dados do app de afiliados (digite)</div>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <input type="number" min="0" value={count} onChange={(e) => setCount(e.target.value)} placeholder="afiliados" title="Nº de afiliados que promoveram o produto" style={small} />
        <select value={period} onChange={(e) => setPeriod(e.target.value)} style={{ ...small, width: "auto" }} title="Janela a que o nº de afiliados se refere">
          {Object.entries(AFFILIATE_PERIODS).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <input type="number" min="0" value={stock} onChange={(e) => setStock(e.target.value)} placeholder="estoque" title="Estoque do vendedor" style={small} />
        <button onClick={save} disabled={saving} style={{ padding: "3px 10px", fontSize: 12, borderRadius: 6, border: "1px solid #5e72e4", background: "#fff", color: "#5e72e4", cursor: "pointer" }}>
          {saving ? "Salvando…" : "Salvar"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
        {level && (
          <span style={{ background: level.bg, color: level.color, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
            {isLiveOpportunity({ ...product, ...saved }) ? "🎯 oportunidade · " : ""}
            {level.label}
          </span>
        )}
        {stockInfo && (
          <span style={{ background: stockInfo.bg, color: stockInfo.color, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
            {stockInfo.label} ({saved.manual_stock})
          </span>
        )}
      </div>
      <div style={{ color: "#8898aa", marginTop: 4 }}>
        A API da Shopee não informa afiliados nem estoque — leia no app de afiliados e digite. Compare contagens só do mesmo período.
      </div>
      {err && <div style={{ color: "#f5365c", marginTop: 4 }}>{err}</div>}

      <div style={{ color: "#525f7f", margin: "10px 0 4px", fontWeight: 600 }}>Hashtags para o vídeo</div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {tags.map((t) => (
          <span key={t} style={{ background: "#eef2ff", color: "#5e72e4", borderRadius: 999, padding: "2px 8px" }}>
            {t}
          </span>
        ))}
      </div>
      <button onClick={copyTags} style={{ marginTop: 6, padding: "3px 10px", fontSize: 12, borderRadius: 6, border: "1px solid #dde3ec", background: "#fff", cursor: "pointer" }}>
        {copied ? "Copiado ✓" : "Copiar todas"}
      </button>
      <div style={{ color: "#8898aa", marginTop: 4 }}>
        Sugeridas pelo título do produto + tags fixas de vídeo/afiliado. A Shopee não publica visualizações por hashtag, então não há ranking de popularidade.
      </div>
    </div>
  );
}

// Quick-view de um produto do catálogo ainda fora (ou já dentro) do
// portfólio. Fora: mostra os dados reais extraídos do marketplace + o botão
// de afiliação. Dentro: abre direto o drawer de gestão do funil, que já sabe
// quais transições de estado são válidas a partir de onde o item está.
export default function ProductCardModal({ product, portfolioItem, onClose, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [justAdded, setJustAdded] = useState(null);
  const [comparables, setComparables] = useState(null);
  const [dl, setDl] = useState({ state: "idle", text: "" });

  useEffect(() => {
    getJSON(`/catalog/products/${product.id}/comparables`)
      .then(setComparables)
      .catch(() => setComparables([]));
  }, [product.id]);

  if (portfolioItem || justAdded) {
    return (
      <ProductDetailDrawer
        portfolioItem={portfolioItem || justAdded}
        onClose={onClose}
        onChanged={() => {
          onChanged();
          onClose();
        }}
      />
    );
  }

  async function affiliate() {
    setAdding(true);
    setError("");
    try {
      const item = await postJSON("/portfolio/items", { product_id: product.id });
      setJustAdded(item);
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  }

  const image = product.images?.[0];

  async function downloadImages() {
    setDl({ state: "loading", text: "" });
    try {
      const r = await postJSON(`/catalog/products/${product.id}/download-images`, {});
      setDl({ state: "ok", text: `${r.files.length} foto(s) salva(s) em ${r.folder}` });
    } catch (e) {
      setDl({ state: "error", text: e.message });
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(23,43,77,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 16,
          width: "min(640px, 100%)",
          maxHeight: "88vh",
          overflowY: "auto",
          boxShadow: "0 20px 60px rgba(23,43,77,.35)",
        }}
      >
        <div style={{ display: "flex", gap: 16, padding: 20 }}>
          <div style={{ width: 160, flexShrink: 0, borderRadius: 10, overflow: "hidden", background: "#f6f9fc", aspectRatio: "1 / 1" }}>
            {image ? (
              <img src={image} alt={product.title} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#c1c9d6", fontSize: 12 }}>
                sem foto
              </div>
            )}
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div style={{ fontSize: 11, color: "#8898aa", textTransform: "uppercase" }}>{product.marketplace}</div>
              <button onClick={onClose} style={{ border: "none", background: "transparent", fontSize: 20, cursor: "pointer", color: "#8898aa" }}>
                ×
              </button>
            </div>
            <h5 style={{ margin: "2px 0 8px", color: "#32325d" }}>{product.title}</h5>

            <ApprovalBadge product={product} />

            <ProductIdRow product={product} />

            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: "#32325d" }}>{fmtMoney(product.price, product.currency)}</span>
              {product.original_price > product.price && (
                <span style={{ fontSize: 13, color: "#8898aa", textDecoration: "line-through" }}>
                  {fmtMoney(product.original_price, product.currency)}
                </span>
              )}
              {product.discount_pct > 0 && (
                <span style={{ fontSize: 12, fontWeight: 700, color: "#f5365c" }}>-{Math.round(product.discount_pct)}%</span>
              )}
            </div>

            <div style={{ fontSize: 12, color: "#525f7f", marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap" }}>
              <span>{product.rating != null ? `⭐ ${product.rating.toFixed(1)} (${product.review_count ?? 0})` : "sem avaliação"}</span>
              <span>{product.sold_quantity ? `${product.sold_quantity} vendido(s)` : "sem dado de vendas"}</span>
              {product.scores?.OPPORTUNITY != null && <span>Oportunidade: {product.scores.OPPORTUNITY.toFixed(0)}/100</span>}
            </div>

            <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {product.affiliate_commission_pct != null ? (
                <span
                  title={product.attributes?.commission_api_pct != null ? `Taxa máxima na API: ${product.attributes.commission_api_pct.toFixed(1)}% (canal redes sociais). No Vídeo: comissão do vendedor + 1,5%.` : undefined}
                  style={{ background: "#e5faf1", color: "#1a7a54", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}
                >
                  {product.attributes?.commission_channel === "shopee_video" ? "comissão Shopee Vídeo " : "comissão "}
                  {product.affiliate_commission_pct.toFixed(1).replace(".0", "")}%
                </span>
              ) : (
                <span style={{ fontSize: 12, color: "#8898aa" }}>comissão não informada pela API deste marketplace</span>
              )}
              {product.seller_is_official_store && (
                <span style={{ background: "#eef2ff", color: "#5e72e4", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
                  loja oficial
                </span>
              )}
              {logisticSpeedRank(product) === 3 && (
                <span style={{ background: "#fff4e5", color: "#b8720a", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "3px 10px" }}>
                  ⚡ entrega rápida
                </span>
              )}
            </div>

            <div style={{ fontSize: 12, color: "#525f7f", marginTop: 8 }}>
              Vendedor: {product.seller_nickname || "não identificado"}
              {product.seller_reputation_level && ` · reputação ${product.seller_reputation_level}`}
              {sellerLocation(product) && ` · ${sellerLocation(product)}`}
              {shipsFromBrazil(product) && " · despacha do Brasil"}
            </div>

            {priceCompetitiveness(product) && (
              <div
                style={{
                  fontSize: 12,
                  marginTop: 8,
                  padding: "8px 10px",
                  borderRadius: 8,
                  background: priceCompetitiveness(product).isLowest ? "#e5faf1" : "#fef1f4",
                  color: priceCompetitiveness(product).isLowest ? "#1a7a54" : "#c31e3f",
                }}
              >
                {priceCompetitiveness(product).confirmed ? (
                  <>
                    {priceCompetitiveness(product).offers} vendedores anunciam este mesmo produto (confirmado pelo
                    catálogo da Mercado Livre), de{" "}
                  </>
                ) : (
                  <>
                    {priceCompetitiveness(product).offers} ofertas parecidas apareceram na mesma busca (a Shopee não
                    confirma se é o item idêntico), de{" "}
                  </>
                )}
                {fmtMoney(priceCompetitiveness(product).min, product.currency)} a{" "}
                {fmtMoney(priceCompetitiveness(product).max, product.currency)}.{" "}
                {priceCompetitiveness(product).isLowest
                  ? "Este é o menor preço — dá pra competir."
                  : "Este não é o menor preço encontrado."}
              </div>
            )}

            {comparables?.length > 0 && (
              <div style={{ fontSize: 12, marginTop: 8 }}>
                <div style={{ color: "#525f7f", marginBottom: 4 }}>Mesmo produto visto em outro anúncio/marketplace:</div>
                {comparables.slice(0, 4).map((c) => (
                  <div key={c.id} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", color: "#8898aa" }}>
                    <span>{c.marketplace}</span>
                    <span>{fmtMoney(c.price, c.currency)}</span>
                  </div>
                ))}
              </div>
            )}

            {product.marketplace === "shopee" && <CompetitionAndHashtags product={product} />}

            {(product.affiliate_url || product.product_url) && (
              <a
                href={product.affiliate_url || product.product_url}
                target="_blank"
                rel="noreferrer"
                style={{ display: "inline-block", marginTop: 10, fontSize: 12, color: "#5e72e4" }}
              >
                {product.affiliate_url ? "abrir link de afiliado ↗" : "abrir anúncio ↗"}
              </a>
            )}

            {product.images?.length > 0 && (
              <div style={{ marginTop: 8, fontSize: 12 }}>
                <button
                  onClick={downloadImages}
                  disabled={dl.state === "loading"}
                  style={{ padding: "4px 10px", fontSize: 12, borderRadius: 6, border: "1px solid #dde3ec", background: "#fff", cursor: "pointer" }}
                >
                  {dl.state === "loading" ? "Baixando…" : "⬇ Baixar foto do produto"}
                </button>
                {dl.text && (
                  <div style={{ marginTop: 4, color: dl.state === "error" ? "#f5365c" : "#1a7a54", wordBreak: "break-all" }}>{dl.text}</div>
                )}
                <div style={{ color: "#8898aa", marginTop: 2 }}>
                  A API entrega só a foto principal (sem vídeo). Confira os direitos de uso antes de reutilizar.
                </div>
              </div>
            )}

            {error && <div style={{ fontSize: 12, color: "#f5365c", marginTop: 8 }}>{error}</div>}

            <button
              onClick={affiliate}
              disabled={adding}
              style={{
                marginTop: 16,
                width: "100%",
                background: "#2dce89",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "10px 16px",
                fontSize: 14,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              {adding ? "Adicionando…" : "Afiliar-se a este produto"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
