import React, { useEffect, useMemo, useState } from "react";
import { getJSON } from "../lib/apiClient";

const card = { background: "#fff", borderRadius: 12, padding: 18, boxShadow: "0 0 2rem 0 rgba(136,152,170,.15)" };

const STATE_LABELS = {
  DISCOVERED: "Vinculado",
  ANALYZING: "Em análise",
  WATCHLIST: "Em observação",
  RECOMMENDED: "Recomendado",
  AFFILIATION_PENDING: "Afiliação pendente",
  AFFILIATED: "Afiliado",
  PORTFOLIO_ACTIVE: "No portfólio",
  CREATIVE_PENDING: "Criativo pendente",
  READY_TO_PUBLISH: "Pronto p/ publicar",
  PUBLISHED: "Publicado",
  MONITORING: "Monitorando",
  OPTIMIZATION_REQUIRED: "Otimizar",
  SCALING: "Escalando",
  PAUSED: "Pausado",
};

const brl = (v) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("pt-BR") : "—");

function Metric({ label, value, tone }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "#8898aa", textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: tone || "#32325d" }}>{value}</div>
    </div>
  );
}

function Chip({ children, color = "#8898aa" }) {
  return (
    <span style={{ fontSize: 10, fontWeight: 700, color, background: `${color}1f`, borderRadius: 999, padding: "2px 8px" }}>
      {children}
    </span>
  );
}

function ProductRow({ row, rank, showClicks }) {
  const sold = row.units > 0;
  const link = row.product_url || row.affiliate_url;
  return (
    <div style={{ ...card, display: "grid", gridTemplateColumns: "28px 64px 1.6fr repeat(5, 1fr)", gap: 14, alignItems: "center", marginBottom: 10, padding: 14 }}>
      <div style={{ fontSize: 16, fontWeight: 800, color: "#5e72e4" }}>#{rank}</div>
      <div style={{ width: 64, height: 64, borderRadius: 8, overflow: "hidden", background: "#f6f9fc" }}>
        {row.image ? (
          <img src={row.image} alt="" loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#c1c9d6" }}>sem foto</div>
        )}
      </div>
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#32325d",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {row.title || "Produto sem nome informado"}
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 5, flexWrap: "wrap", alignItems: "center" }}>
          {row.product_external_id && <span style={{ fontSize: 10, color: "#8898aa" }}>ID {row.product_external_id}</span>}
          {row.portfolio_state && <Chip color="#5e72e4">{STATE_LABELS[row.portfolio_state] || row.portfolio_state}</Chip>}
          {!row.product_id && <Chip>fora do catálogo</Chip>}
          {row.commission_pct != null && <Chip color="#2dce89">comissão anunciada {row.commission_pct}%</Chip>}
          {row.cancelled_orders > 0 && <Chip color="#f5365c">{row.cancelled_orders} cancelada(s)</Chip>}
          {link && (
            <a href={link} target="_blank" rel="noreferrer" style={{ fontSize: 10, color: "#5e72e4" }}>
              abrir ↗
            </a>
          )}
        </div>
      </div>
      <Metric label="Unidades" value={sold ? row.units : "0"} tone={sold ? undefined : "#c1c9d6"} />
      <Metric label="Receita" value={sold ? brl(row.revenue) : "—"} />
      <Metric label="Comissão confirmada" value={row.commission_confirmed > 0 ? brl(row.commission_confirmed) : "—"} tone="#1a7a54" />
      <Metric label="Comissão pendente" value={row.commission_estimated > 0 ? brl(row.commission_estimated) : "—"} tone="#8a6d1d" />
      {showClicks ? (
        <Metric label="Cliques" value={row.clicks != null ? row.clicks : "—"} />
      ) : (
        <Metric label={sold ? "Última venda" : "Preço"} value={sold ? day(row.last_sale_at) : brl(row.price)} />
      )}
    </div>
  );
}

function Section({ title, hint, children }) {
  return (
    <section style={{ marginBottom: 26 }}>
      <h6 style={{ color: "#32325d", margin: "0 0 4px" }}>{title}</h6>
      <div style={{ fontSize: 12, color: "#8898aa", marginBottom: 10 }}>{hint}</div>
      {children}
    </section>
  );
}

function Empty({ children }) {
  return <div style={{ ...card, fontSize: 13, color: "#8898aa" }}>{children}</div>;
}

export default function ProdutosDesempenho({ marketplace }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    setError("");
    getJSON(`/performance/products?marketplace=${marketplace}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [marketplace]);

  const view = useMemo(() => {
    const rows = data?.products || [];
    const byUnits = (a, b) => b.units - a.units || b.revenue - a.revenue;
    return {
      rows,
      top: rows.filter((r) => r.units > 0).sort(byUnits).slice(0, 10),
      least: [...rows].sort((a, b) => a.units - b.units || a.revenue - b.revenue).slice(0, 10),
      clicks: data?.clicks_tracked
        ? rows.filter((r) => r.clicks != null).sort((a, b) => b.clicks - a.clicks).slice(0, 10)
        : [],
      totals: rows.reduce(
        (t, r) => ({
          sold: t.sold + (r.units > 0 ? 1 : 0),
          units: t.units + r.units,
          revenue: t.revenue + r.revenue,
          confirmed: t.confirmed + r.commission_confirmed,
          pending: t.pending + r.commission_estimated,
        }),
        { sold: 0, units: 0, revenue: 0, confirmed: 0, pending: 0 }
      ),
    };
  }, [data]);

  if (error) return <p style={{ color: "#f5365c" }}>Não foi possível carregar o desempenho ({error}).</p>;
  if (!data) return <p style={{ color: "#8898aa" }}>Carregando...</p>;

  const { rows, top, least, clicks, totals } = view;

  if (rows.length === 0) {
    return (
      <Empty>
        Nenhuma venda registrada nem produto vinculado neste marketplace. As vendas vêm da última coleta
        (<code>scripts/ingest.py --sales</code>, janela de 30 dias); produtos que você afiliou direto no app do
        marketplace só aparecem aqui depois da primeira venda ou de serem vinculados em Portfólio.
      </Empty>
    );
  }

  return (
    <div>
      <div style={{ ...card, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 22 }}>
        <Metric label="Produtos com venda" value={`${totals.sold} de ${rows.length}`} />
        <Metric label="Unidades vendidas" value={totals.units} />
        <Metric label="Receita" value={brl(totals.revenue)} />
        <Metric label="Comissão confirmada" value={brl(totals.confirmed)} tone="#1a7a54" />
        <Metric label="Comissão pendente" value={brl(totals.pending)} tone="#8a6d1d" />
      </div>

      <Section title="Mais vendidos" hint="Por unidades vendidas (vendas canceladas não contam). Janela: últimos 30 dias da coleta.">
        {top.length === 0 ? (
          <Empty>Nenhum produto deste marketplace vendeu ainda.</Empty>
        ) : (
          top.map((r, i) => <ProductRow key={`${r.product_external_id}-${i}`} row={r} rank={i + 1} />)
        )}
      </Section>

      <Section title="Menos vendidos" hint="Produtos vinculados que não venderam aparecem primeiro, com tudo da sua filiação (estado, preço, comissão anunciada).">
        {rows.length < 2 ? (
          <Empty>Só há um produto registrado — o ranking de menos vendidos só faz sentido com mais de um.</Empty>
        ) : (
          least.map((r, i) => <ProductRow key={`${r.product_external_id}-${i}`} row={r} rank={i + 1} />)
        )}
      </Section>

      <Section title="Mais cliques" hint="Cliques nos seus links rastreados (não conta robôs; não é visualização do post).">
        {!data.clicks_tracked ? (
          <Empty>
            Ainda não há cliques registrados. A API da Shopee só informa cliques que viraram compra; para contar todos,
            as divulgações precisam usar o <strong>link rastreado</strong> (abra um produto vinculado e clique em
            "Criar link rastreado", ou peça ao agente). Produtos sem link rastreado mostram "—", nunca um zero inventado.
          </Empty>
        ) : clicks.length === 0 ? (
          <Empty>Nenhum clique registrado para os produtos deste marketplace.</Empty>
        ) : (
          clicks.map((r, i) => <ProductRow key={`${r.product_external_id}-${i}`} row={r} rank={i + 1} showClicks />)
        )}
      </Section>
    </div>
  );
}
