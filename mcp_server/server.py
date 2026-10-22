"""Servidor MCP do marketTon: as ferramentas que o agente Claude recebe.

Duas famílias, com regras diferentes:

* **Consulta** (sempre disponível): estado do sistema, checklist, produtos, funil,
  oportunidades de busca, vendas. Não altera nada.
* **Ação** (só com o "modo agente" ligado no marketTon): vincular produto ao
  portfólio, mover estado, registrar sinais manuais, aplicar comissão observada. A
  recusa vem da própria API — este servidor não decide nem contorna nada.

O que NÃO existe aqui (e por quê) está em `docs/mcp-agent.md`: o agente não mexe em
credenciais nem usuários, e não edita anúncios dos marketplaces nem campanhas, porque a
API do marketTon não expõe essas ações. Quando uma capacidade for criada na API,
ela vira uma ferramenta aqui.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcp_server.client import ApiError, MarkettonClient

AGENT_NAME = "claude_agent"

INSTRUCTIONS = """\
Você administra o marketTon, um sistema de inteligência para afiliados (Shopee, Mercado Livre).

Princípios:
- Nunca invente dado. Se uma ferramenta devolver null/"sem dado", diga isso.
- Comece por `marketton_status` e `marketton_checklist` para saber o que falta.
- Para escolher produto, use `product_funnel`: ele separa DEMANDA (o produto vende?) de TRÁFEGO PAGO
  (anunciar compensa?). O operador divulga de forma orgânica; demanda é o que decide.
- Ferramentas de ação só funcionam com o "modo agente" ligado. Se a API recusar por isso, avise o
  usuário em vez de tentar outro caminho.
- Antes de uma ação que muda o portfólio, explique o motivo (dados que a sustentam) e depois execute.
"""

mcp = FastMCP("marketton", instructions=INSTRUCTIONS)
_client = MarkettonClient()

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

_PRODUCT_FIELDS = (
    "id", "marketplace", "external_id", "title", "price", "currency", "affiliate_commission_pct",
    "sold_quantity", "rating", "review_count", "ranking_position", "seller_nickname", "seller_reputation_level",
    "seller_is_official_store", "competing_offers", "affiliate_count", "affiliate_count_period", "scores", "product_url",
)


def _slim(product: dict) -> dict:
    return {k: product.get(k) for k in _PRODUCT_FIELDS if k in product}


def _run(fn: Callable[[], Any]) -> Any:
    """Executa a chamada e transforma erro da API em texto que o agente entende."""
    try:
        return fn()
    except ApiError as exc:
        if exc.agent_mode_off:
            return {
                "ok": False,
                "agent_mode": "desligado",
                "message": "O modo agente está desligado no marketTon: eu só posso consultar. "
                "Peça ao usuário para ativar a administração pelo agente (botão no topo do app).",
            }
        return {"ok": False, "status": exc.status, "message": str(exc)}


# --- Consulta ---------------------------------------------------------------------


@mcp.tool(annotations=READ)
def marketton_status() -> Any:
    """Estado geral: modo agente, integrações (sem segredos) e contagens de catálogo, portfólio e vendas."""
    return _run(lambda: _client.get("/agent/status"))


@mcp.tool(annotations=READ)
def marketton_checklist() -> Any:
    """O que falta fazer para vender: lacunas objetivas, da mais à menos grave, com como resolver."""
    return _run(lambda: _client.get("/agent/checklist"))


@mcp.tool(annotations=READ)
def list_products(
    marketplace: str | None = None,
    search: str | None = None,
    min_commission_pct: float | None = None,
    limit: int = 20,
) -> Any:
    """Produtos do catálogo (sugeridos). `marketplace`: mercado_livre | shopee. `search` filtra pelo título."""

    def go() -> Any:
        rows = _client.get(
            "/catalog/products", marketplace=marketplace, search=search,
            min_commission_pct=min_commission_pct, limit=max(1, min(limit, 100)),
        )
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return [_slim(p) for p in rows]

    return _run(go)


@mcp.tool(annotations=READ)
def get_product(product_id: int) -> Any:
    """Detalhe de um produto do catálogo (preço, vendedor, comissão, sinais de demanda)."""
    return _run(lambda: _slim(_client.get(f"/catalog/products/{product_id}")))


@mcp.tool(annotations=READ)
def product_funnel(product_id: int, keyword: str | None = None, conversion_pct: float = 1.5) -> Any:
    """Funil de venda do produto: Google Trends + Google Ads (volume, CPC, disputa) + economia da comissão.

    Devolve dois vereditos separados: `demand_verdict` (o produto tem procura?) e `ads_verdict`
    (anunciar compensa?). `keyword` é opcional (sugerida a partir do título). `conversion_pct` é uma
    premissa (% de cliques que viram compra), não um dado medido. Demora alguns segundos.
    """
    return _run(lambda: _client.get(
        f"/catalog/products/{product_id}/funnel", keyword=keyword, conversion_pct=conversion_pct))


@mcp.tool(annotations=READ)
def search_opportunities(keywords: list[str] | None = None, limit: int = 5) -> Any:
    """Oportunidades de busca: tendência do Google Trends (+ volume/CPC/disputa se o Google Ads estiver conectado)."""
    return _run(lambda: _client.get(
        "/trends/opportunities", keywords=",".join(keywords) if keywords else None, limit=limit))


@mcp.tool(annotations=READ)
def trending_abroad(sites: str = "MLM,MCO,MLC", limit_per_site: int = 10) -> Any:
    """Mais vendidos de México, Colômbia e Chile no Mercado Livre, com correspondência no catálogo brasileiro."""
    return _run(lambda: _client.get("/catalog/trending-abroad", sites=sites, limit_per_site=limit_per_site))


@mcp.tool(annotations=READ)
def sales_performance(marketplace: str | None = None) -> Any:
    """Vendas, receita e comissão (confirmada x pendente) por produto afiliado. Cliques não são rastreados."""
    return _run(lambda: _client.get("/performance/products", marketplace=marketplace))


@mcp.tool(annotations=READ)
def list_portfolio(marketplace: str | None = None) -> Any:
    """Produtos já vinculados à conta, com o estado de cada um no funil de afiliação."""
    return _run(lambda: _client.get("/portfolio/items", marketplace=marketplace, limit=200))


@mcp.tool(annotations=READ)
def commission_proposals(marketplace: str | None = None, min_sales: int = 1) -> Any:
    """Produtos sem comissão que já venderam, com a taxa observada nas vendas (não grava nada)."""
    return _run(lambda: _client.get("/agent/commissions/proposals", marketplace=marketplace, min_sales=min_sales))


@mcp.tool(annotations=READ)
def daily_review() -> Any:
    """Revisão diária em uma chamada: status, checklist, comissões aprendíveis e vendas por marketplace.

    Pensada para rodar todo dia (agendada ou manual) e abrir a conversa com um resumo do que importa.
    """

    def go() -> Any:
        status = _client.get("/agent/status")
        checklist = _client.get("/agent/checklist")
        commissions = _client.get("/agent/commissions/proposals")
        perf = _client.get("/performance/products")
        products = perf.get("products", []) if isinstance(perf, dict) else []
        by_mp: dict[str, dict] = {}
        for row in products:
            agg = by_mp.setdefault(row["marketplace"], {"products": 0, "units": 0, "revenue": 0.0, "commission_confirmed": 0.0, "commission_pending": 0.0})
            agg["products"] += 1
            agg["units"] += row.get("units", 0)
            agg["revenue"] += row.get("revenue", 0.0)
            agg["commission_confirmed"] += row.get("commission_confirmed", 0.0)
            agg["commission_pending"] += row.get("commission_estimated", 0.0)
        return {
            "status": status,
            "checklist": checklist,
            "commissions_to_learn": commissions,
            "sales_by_marketplace": by_mp,
            "note": "Cliques não são rastreados; 'pending' é comissão estimada, ainda não confirmada.",
        }

    return _run(go)


# --- Ação (exigem o modo agente ligado) -------------------------------------------


@mcp.tool(annotations=WRITE)
def add_to_portfolio(product_id: int, notes: str | None = None) -> Any:
    """Vincula um produto do catálogo ao portfólio (estado inicial). EXIGE o modo agente ligado.

    Use depois de conferir o `product_funnel`; explique ao usuário o motivo da escolha.
    """
    return _run(lambda: _client.post(
        "/portfolio/items", {"product_id": product_id, "added_by": AGENT_NAME, "notes": notes}))


@mcp.tool(annotations=WRITE)
def move_portfolio_item(item_id: int, to_state: str, reason: str) -> Any:
    """Move um item do portfólio para outro estado (ex.: AFFILIATION_PENDING, AFFILIATED, PAUSED, REMOVED).

    EXIGE o modo agente ligado. `reason` é obrigatório e vai para a trilha de auditoria. A API valida a
    transição e devolve as permitidas se ela não for válida.
    """
    return _run(lambda: _client.post(
        f"/portfolio/items/{item_id}/transition", {"to_state": to_state, "actor": AGENT_NAME, "reason": reason}))


@mcp.tool(annotations=WRITE)
def set_manual_signals(
    product_id: int,
    affiliate_count: int | None = None,
    affiliate_count_period: str | None = None,
    manual_stock: int | None = None,
) -> Any:
    """Registra nº de afiliados (período: total | semana | mes) e estoque de um produto. EXIGE o modo agente ligado.

    São dados lidos no app de afiliados, que nenhuma API expõe: só registre o que o usuário informou.
    """
    return _run(lambda: _client.put(
        f"/catalog/products/{product_id}/manual-signals",
        {"affiliate_count": affiliate_count, "affiliate_count_period": affiliate_count_period, "manual_stock": manual_stock}))


@mcp.tool(annotations=WRITE)
def apply_observed_commissions(marketplace: str | None = None, min_sales: int = 1) -> Any:
    """Preenche a comissão dos produtos que não têm, usando a taxa observada nas vendas. EXIGE o modo agente ligado.

    Nunca sobrescreve comissão vinda da API ou digitada pelo operador. Mostre antes `commission_proposals`.
    """
    return _run(lambda: _client.post("/agent/commissions/apply", marketplace=marketplace, min_sales=min_sales))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
