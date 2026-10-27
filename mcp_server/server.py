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
# Sem `from __future__ import annotations` de propósito: versões antigas do SDK do MCP (1.12 e anteriores)
# examinam a anotação dos parâmetros das ferramentas e quebram quando ela vira texto ("str | None").

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcp_server.client import ApiError, MarkettonClient

AGENT_NAME = "claude_agent"

INSTRUCTIONS = """\
Você administra o marketTon, um sistema de inteligência para afiliados (Shopee, Mercado Livre).

Comece por `chat_inbox` (o que o operador pediu) e consulte `agent_playbook` (seu manual) só na seção de que precisa, com `section`.
Seja econômico: cada chamada e cada token custam ao operador.
Fale com o operador pelo chat (`chat_send`); peça recursos que faltam com `request_resource`.

Princípios:
- Nunca invente dado. Se uma ferramenta devolver null/"sem dado", diga isso.
- Comece por `marketton_status` e `marketton_checklist` para saber o que falta.
- Para escolher produto, use `product_funnel`: ele separa DEMANDA (o produto vende?) de TRÁFEGO PAGO
  (anunciar compensa?). O operador divulga de forma orgânica; demanda é o que decide.
- Seu nível de autonomia está em `marketton_status` (agent_mode.autonomy): `supervised` = explique antes de agir e
  peça aprovação para remover; `independent` = execute e relate. Falta de credencial não para o trabalho: use o que existe.
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


def _run(fn: Callable[[], Any]):
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
def marketton_status():
    """Estado geral: modo agente, integrações (sem segredos) e contagens de catálogo, portfólio e vendas."""
    return _run(lambda: _client.get("/agent/status"))


@mcp.tool(annotations=READ)
def marketton_checklist():
    """O que falta fazer para vender: lacunas objetivas, da mais à menos grave, com como resolver."""
    return _run(lambda: _client.get("/agent/checklist"))


@mcp.tool(annotations=READ)
def list_products(
    marketplace: str | None = None,
    search: str | None = None,
    min_commission_pct: float | None = None,
    limit: int = 20,
):
    """Produtos do catálogo (sugeridos). `marketplace`: mercado_livre | shopee. `search` filtra pelo título."""

    def go():
        rows = _client.get(
            "/catalog/products", marketplace=marketplace, search=search,
            min_commission_pct=min_commission_pct, limit=max(1, min(limit, 100)),
        )
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return [_slim(p) for p in rows]

    return _run(go)


@mcp.tool(annotations=READ)
def get_product(product_id: int):
    """Detalhe de um produto do catálogo (preço, vendedor, comissão, sinais de demanda)."""
    return _run(lambda: _slim(_client.get(f"/catalog/products/{product_id}")))


@mcp.tool(annotations=READ)
def product_funnel(product_id: int, keyword: str | None = None, conversion_pct: float = 1.5):
    """Funil de venda do produto: Google Trends + Google Ads (volume, CPC, disputa) + economia da comissão.

    Devolve dois vereditos separados: `demand_verdict` (o produto tem procura?) e `ads_verdict`
    (anunciar compensa?). `keyword` é opcional (sugerida a partir do título). `conversion_pct` é uma
    premissa (% de cliques que viram compra), não um dado medido. Demora alguns segundos.
    """
    return _run(lambda: _client.get(
        f"/catalog/products/{product_id}/funnel", keyword=keyword, conversion_pct=conversion_pct))


@mcp.tool(annotations=READ)
def search_opportunities(keywords: list[str] | None = None, limit: int = 5):
    """Oportunidades de busca: tendência do Google Trends (+ volume/CPC/disputa se o Google Ads estiver conectado)."""
    return _run(lambda: _client.get(
        "/trends/opportunities", keywords=",".join(keywords) if keywords else None, limit=limit))


@mcp.tool(annotations=READ)
def radar_status(limit: int = 10, only_rising: bool = True):
    """Radar de tendências do Google (medido por código todo dia): crescimento da busca em 7, 15 e 30 dias, volume mensal, CPC e disputa.

    Só as palavras que estão SUBINDO por padrão. Ao achar uma: veja se o catálogo tem o produto (`list_products`), traga mais com
    `refresh_catalog(keywords=[...])`, confira a conta (CPC ÷ comissão por venda = conversão para empatar) e proponha a campanha. Não repita
    a análise de palavras que você já tratou.
    """
    return _run(lambda: _client.get("/trends/radar", limit=max(1, min(int(limit), 30)), only_rising=only_rising))


@mcp.tool(annotations=WRITE)
def radar_watch(add: list[str] | None = None, remove: list[str] | None = None):
    """Põe palavras na vigilância do radar (até 40; o radar olha 12 por dia) ou tira. Use termos de produto que o público busca
    (ex.: "tênis running", "lanterna tática"). Ideias de outros países (`trending_abroad`) entram aqui traduzidas. EXIGE o modo agente."""
    return _run(lambda: _client.post("/trends/radar/watch", {"add": add or [], "remove": remove or []}))


@mcp.tool(annotations=READ)
def trending_abroad(sites: str = "MLM,MCO,MLC", limit_per_site: int = 10):
    """Mais vendidos de México, Colômbia e Chile no Mercado Livre, com correspondência no catálogo brasileiro."""
    return _run(lambda: _client.get("/catalog/trending-abroad", sites=sites, limit_per_site=limit_per_site))


@mcp.tool(annotations=READ)
def sales_performance(marketplace: str | None = None):
    """Vendas, receita e comissão (confirmada x pendente) por produto afiliado. Cliques não são rastreados."""
    return _run(lambda: _client.get("/performance/products", marketplace=marketplace))


@mcp.tool(annotations=READ)
def list_portfolio(marketplace: str | None = None):
    """Produtos já vinculados à conta, com o estado de cada um no funil de afiliação."""
    return _run(lambda: _client.get("/portfolio/items", marketplace=marketplace, limit=200))


@mcp.tool(annotations=READ)
def commission_proposals(marketplace: str | None = None, min_sales: int = 1):
    """Produtos sem comissão que já venderam, com a taxa observada nas vendas (não grava nada)."""
    return _run(lambda: _client.get("/agent/commissions/proposals", marketplace=marketplace, min_sales=min_sales))


@mcp.tool(annotations=READ)
def daily_review():
    """Revisão diária em uma chamada: status, checklist, comissões aprendíveis e vendas por marketplace.

    Pensada para rodar todo dia (agendada ou manual) e abrir a conversa com um resumo do que importa.
    """

    def go():
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
def add_to_portfolio(product_id: int, notes: str | None = None):
    """Vincula um produto do catálogo ao portfólio (estado inicial). EXIGE o modo agente ligado.

    Use depois de conferir o `product_funnel`; explique ao usuário o motivo da escolha.
    """
    return _run(lambda: _client.post(
        "/portfolio/items", {"product_id": product_id, "added_by": AGENT_NAME, "notes": notes}))


@mcp.tool(annotations=WRITE)
def move_portfolio_item(item_id: int, to_state: str, reason: str):
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
):
    """Registra nº de afiliados (período: total | semana | mes) e estoque de um produto. EXIGE o modo agente ligado.

    São dados lidos no app de afiliados, que nenhuma API expõe: só registre o que o usuário informou.
    """
    return _run(lambda: _client.put(
        f"/catalog/products/{product_id}/manual-signals",
        {"affiliate_count": affiliate_count, "affiliate_count_period": affiliate_count_period, "manual_stock": manual_stock}))


@mcp.tool(annotations=WRITE)
def apply_observed_commissions(marketplace: str | None = None, min_sales: int = 1):
    """Preenche a comissão dos produtos que não têm, usando a taxa observada nas vendas. EXIGE o modo agente ligado.

    Nunca sobrescreve comissão vinda da API ou digitada pelo operador. Mostre antes `commission_proposals`.
    """
    return _run(lambda: _client.post("/agent/commissions/apply", marketplace=marketplace, min_sales=min_sales))


# --- Conversa, saúde e vendas ------------------------------------------------------------

PLAYBOOK = Path(__file__).resolve().parent.parent / "docs" / "agent-playbook.md"


@mcp.tool(annotations=READ)
def agent_playbook(section: str | None = None) -> str:
    """O manual do agente (regras, rotina, escolha de produto, conteúdo, recalibragem).

    Sem `section` devolve o manual inteiro; com `section` ("1", "2", "3.05"…) devolve só essa seção e economiza leitura.
    """
    try:
        text = PLAYBOOK.read_text(encoding="utf-8")
    except OSError:
        return "Manual não encontrado em docs/agent-playbook.md."
    if not section:
        return text
    wanted = section.strip().rstrip(".")
    blocks = re.split(r"(?m)^(?=## )", text)
    titles = [b.splitlines()[0] for b in blocks if b.startswith("## ")]
    picked = [b for b in blocks if b.startswith("## ") and b[3:].split()[0].rstrip(".") == wanted]
    return "".join(picked).strip() or f"Seção '{section}' não existe. Seções: " + " | ".join(titles)


@mcp.tool(annotations=READ)
def chat_inbox():
    """Mensagens novas do operador e do sistema + tarefas abertas (ex.: rotina de ativação). Marca como lido."""
    return _run(lambda: _client.get("/agent/chat/inbox"))


@mcp.tool(annotations=WRITE)
def chat_send(text: str, kind: str = "message"):
    """Escreve no chat do operador. `kind`: message (conversa) ou report (relatório curto). Funciona mesmo com o modo agente desligado."""
    return _run(lambda: _client.post("/agent/chat", {"text": text, "kind": kind if kind in ("message", "report") else "message"}))


@mcp.tool(annotations=READ)
def finance_summary(days: int = 7):
    """Resumo financeiro curto: vendas, comissão (confirmada x pendente), gasto com anúncios, resultado e saldo total das carteiras.

    Só os números do período (sem a série diária). Use no relatório e para decidir onde pôr verba; não lança saldo.
    """
    def pick(d):
        return {"periodo": f"{d['from']} a {d['to']}", **d["kpis"], "carteiras": d["wallets"]["total_brl"],
                "carteiras_informadas": f"{d['wallets']['known']} de {d['wallets']['of']}",
                "por_plataforma": [{k: v[k] for k in ("label", "sales", "confirmed_brl", "pending_brl")} for v in d["by_platform"]]}
    return _run(lambda: pick(_client.get(f"/finance/overview?days={max(1, min(int(days), 90))}")))


@mcp.tool(annotations=WRITE)
def report_add(kind: str, title: str, body: str = ""):
    """Registra uma linha no relatório do operador (página Relatórios). `kind`: achado (o que viu), acao (o que fez),
    ideia (nova forma de vender) ou alerta (precisa de atenção). `title` curto; `body` em até 3 linhas. Não repita o chat."""
    return _run(lambda: _client.post("/agent/reports", {"kind": kind, "title": title, "body": body or None}))


@mcp.tool(annotations=WRITE)
def request_resource(resource: str, why: str, how_to_provide: str):
    """Pede ao operador um recurso, acesso ou ferramenta que falta (aparece como cartão no chat).

    `resource`: o que precisa (ex.: "Chave da API do AI Studio"). `why`: o que isso destrava. `how_to_provide`:
    onde o operador coloca (ex.: "Integrações > ..."). Nunca peça senha ou token no chat: o operador os cadastra no app.
    """
    text = f"**{resource}**\nPor quê: {why}\nComo fornecer: {how_to_provide}"
    return _run(lambda: _client.post("/agent/chat", {
        "text": text, "kind": "request", "meta": {"resource": resource, "why": why, "how": how_to_provide}}))


@mcp.tool(annotations=WRITE)
def complete_task(task_id: int):
    """Marca como concluída uma tarefa da caixa de entrada (ex.: a rotina de ativação), depois de postar o relatório."""
    return _run(lambda: _client.request("PATCH", f"/agent/chat/{task_id}", json={"status": "done"}))


@mcp.tool(annotations=READ)
def system_health():
    """Saúde do sistema: banco, frescor do catálogo e das vendas, integrações, jobs com falha e pedidos abertos."""
    return _run(lambda: _client.get("/agent/health"))


@mcp.tool(annotations=READ)
def capabilities():
    """O que está pronto, o que falta o operador configurar e o que ainda não foi construído (base para pedir recursos)."""
    return _run(lambda: _client.get("/agent/capabilities"))


@mcp.tool(annotations=WRITE)
def sync_sales(since_days: int = 30):
    """Busca as vendas dos marketplaces, aprende comissão e avisa cada venda nova no chat. EXIGE o modo agente ligado."""
    return _run(lambda: _client.post("/agent/sales/sync", since_days=since_days))


@mcp.tool(annotations=WRITE)
def refresh_catalog(marketplaces: list[str] | None = None, keywords: list[str] | None = None, limit: int = 50):
    """Atualiza o catálogo (coleta de produtos + score) em segundo plano. EXIGE o modo agente ligado.

    Use quando `system_health` mostrar o catálogo velho (mais de 2 dias) ou quando precisar de produtos de um nicho
    novo (passe `keywords`, até 10, ex.: ["lanterna tática"]). `marketplaces` opcional (mercado_livre, shopee,
    monetizze). Há intervalo mínimo de 6 h por marketplace: se a API recusar por isso, siga trabalhando com o que há
    e tente de novo depois; você não pode forçar. Ao terminar, o resultado cai no chat; confira com
    `catalog_refresh_status`.
    """
    return _run(lambda: _client.post("/agent/catalog/refresh", {
        "marketplaces": marketplaces, "keywords": keywords, "limit": limit, "force": False}))


@mcp.tool(annotations=READ)
def catalog_refresh_status():
    """Estado da última atualização do catálogo: em andamento, quando terminou, resultado e intervalo mínimo."""
    return _run(lambda: _client.get("/agent/catalog/refresh"))


@mcp.tool(annotations=WRITE)
def create_tracked_link(portfolio_item_id: int | None = None, product_id: int | None = None, channel: str = "outro",
                        campaign: str | None = None):
    """Cria o link curto rastreado de um produto para um canal (ex.: instagram, tiktok, youtube, shopee_video). EXIGE o modo agente.

    Use ESTE link, não o link comum, em toda divulgação: ele conta os cliques. Mesmo produto + canal + campanha
    reaproveita o link. `campaign` identifica o ângulo/gancho testado (ex.: "gancho-preco"). Só funciona se o
    produto tem link de afiliado e o encurtador está configurado em Integrações.
    """
    return _run(lambda: _client.post("/links", {
        "portfolio_item_id": portfolio_item_id, "product_id": product_id, "channel": channel, "campaign": campaign}))


@mcp.tool(annotations=WRITE)
def sync_clicks():
    """Busca no redirecionador os cliques novos dos links rastreados e atualiza as contagens. EXIGE o modo agente.

    Faça na rotina da manhã e da noite, antes de comparar o desempenho de ganchos e canais.
    """
    return _run(lambda: _client.post("/links/sync"))


@mcp.tool(annotations=READ)
def creative_estimate(product_id: int, quality: str = "economy", angle: str = "problem_solution", hook_variants: int = 2, formats: str = "video"):
    """Estima custo e prazo dos criativos de um produto no AI Studio, sem gastar. Use antes de `creative_create`.

    `quality`: economy | standard | premium. `angle`: problem_solution | demo | comparison | offer | unboxing | ugc_style. `formats`: video (padrão) | images (só imagens 4:5, 1:1 e 9:16 mais texto, bem mais barato).
    """
    return _run(lambda: _client.post("/creatives/estimate", {"product_id": product_id, "quality": quality, "angle": angle, "hook_variants": hook_variants, "formats": formats}))


@mcp.tool(annotations=WRITE)
def creative_create(product_id: int, mode: str = "sandbox", quality: str = "economy", angle: str = "problem_solution", hook_variants: int = 2, formats: str = "video",
                    notes: str | None = None):
    """Pede ao AI Studio os criativos (vídeo 9:16 e 1:1, imagem 4:5 e texto) de um produto da vitrine. EXIGE o modo agente.

    `mode="sandbox"` (padrão) não gasta nada e devolve peças de exemplo: use para testar o fluxo. `mode="live"` gasta créditos e só funciona
    se o operador ligou a permissão no cartão do AI Studio; peça aprovação no chat antes. Nunca invente alegações: o produto só pode ser descrito
    pelos fatos que o marketTon tem. O resultado chega por webhook; acompanhe com `creative_status`.
    """
    body = {"product_id": product_id, "mode": mode, "quality": quality, "angle": angle, "hook_variants": hook_variants, "formats": formats}
    if notes:
        body["notes"] = notes  # ao REFAZER: o que corrigir (ex.: "título menor, sem cobrir o produto")
    return _run(lambda: _client.post("/creatives", body))


@mcp.tool(annotations=READ)
def creative_status(refresh: bool = True):
    """Campanhas de criativos recentes: estado, custo e as peças prontas (vídeos, imagens e textos). `refresh` reconcilia com o AI Studio."""
    return _run(lambda: _client.get("/creatives", refresh=str(refresh).lower()))


@mcp.tool(annotations=READ)
def ads_budget_status():
    """Orçamento de anúncios POR PLATAFORMA (`meta` e `google`, cada uma com o seu): teto por dia, valor da semana, quanto já está comprometido e o
    gasto lido. O gasto de uma rede não consome o da outra. Consulte antes de planejar."""
    return _run(lambda: _client.get("/ads/budget"))


@mcp.tool(annotations=WRITE)
def ad_create(creative_id: int, daily_brl: float, days: int = 3, dry_run: bool = True, post_id: str | None = None):
    """Cria o anúncio na Meta a partir de um criativo PRONTO. EXIGE o modo agente.

    `dry_run=True` (padrão) só mostra o que seria enviado, sem tocar na Meta: use sempre primeiro e mostre o plano no chat. Com `dry_run=False`
    o anúncio nasce PAUSADO na Meta (nada gasta): quem LIGA é o operador, em Criativos e anúncios; você não consegue ligar. As travas
    (verba por dia, valor da semana, produtos e criativos por produto) são aplicadas pelo sistema e você não as altera. Criativo de teste
    (sandbox) nunca vira anúncio de verdade. Peça a aprovação do plano no chat ANTES de criar.

    `post_id` (opcional): anunciar um post que o operador JÁ publicou na Página (use `meta_page_posts` para achar o id). Serve quando a Meta
    recusa posts criados pelo app. O post precisa levar o link do produto (`meta_post_kit` dá o texto, o link e a imagem para o operador publicar).
    """
    body = {"creative_id": creative_id, "daily_brl": daily_brl, "days": days, "dry_run": dry_run}
    if post_id:
        body["post_id"] = post_id
    return _run(lambda: _client.post("/ads", body))


@mcp.tool(annotations=READ)
def content_pending():
    """Fila de conteúdo: criativos ao vivo prontos que ainda não têm post de imagem e/ou Reel no Instagram, a chave da publicação automática
    (ligada ou não), o teto por dia e quantas publicações saíram hoje. Comece por aqui na rotina de conteúdo (manual 3.09)."""
    return _run(lambda: _client.get("/social/pending"))


@mcp.tool(annotations=READ)
def creative_review(creative_id: int):
    """VER o criativo (imagem 4:5) e, se já montado, o slideshow (4 quadros), com os fatos do produto e a lista do que conferir. Olhe com
    senso crítico: texto cortado, preço errado ou repetido, logo cobrindo algo, produto diferente da foto, marca de terceiros. Depois registre o
    parecer com `creative_review_submit`."""
    try:
        data = _client.get(f"/social/review/{creative_id}")
    except ApiError as exc:
        return {"ok": False, "status": exc.status, "message": str(exc)}
    import base64

    from mcp.server.fastmcp import Image

    out: list = [data["facts"]]
    for item in data["images"]:
        out.append(item["name"])
        out.append(Image(data=base64.b64decode(item["jpeg_b64"]), format="jpeg"))
    return out


@mcp.tool(annotations=WRITE)
def creative_review_submit(creative_id: int, kind: str, verdict: str, notes: str = ""):
    """Registra o seu parecer sobre o que viu: `kind` = image ou reel; `verdict` = approved ou rejected. Recusa precisa do motivo (o que está
    errado). Só com `approved` recente a publicação automática libera. Se recusou, refaça (`creative_create` com `notes`) no máximo 2 vezes por
    produto; passou disso, registre no relatório e não publique."""
    return _run(lambda: _client.post("/social/review", {"creative_id": creative_id, "kind": kind, "verdict": verdict, "notes": notes}))


@mcp.tool(annotations=WRITE)
def reel_build(creative_id: int):
    """Monta o slideshow vertical (10 a 15 s, sem custo de crédito) das imagens do produto. Depois confira com `creative_review`."""
    return _run(lambda: _client.post(f"/social/reel/{creative_id}/build"))


@mcp.tool(annotations=WRITE)
def social_publish(creative_id: int, kind: str, caption: str | None = None):
    """Publica no Instagram do Mural (`kind` = image ou reel). SÓ funciona com a chave da publicação automática ligada pelo operador, parecer
    `approved` seu e recente, texto com o aviso de divulgação e dentro do teto do dia. Sem `caption`, usa o texto sugerido. Anúncios (que gastam
    dinheiro) continuam só do operador. Registre no relatório (`report_add`) o que saiu, com o link."""
    body = {"creative_id": creative_id, "kind": kind}
    if caption:
        body["caption"] = caption
    return _run(lambda: _client.post("/social/auto/publish", body))


@mcp.tool(annotations=READ)
def instagram_caption(creative_id: int):
    """Texto sugerido para o post do Instagram de um criativo pronto (com o link da bio e o aviso de divulgação). Para publicar sozinho use
    `social_publish` (com a chave ligada e o parecer aprovado); senão o operador publica pelo botão em Criativos e anúncios."""
    return _run(lambda: _client.get(f"/social/instagram/caption/{creative_id}"))


@mcp.tool(annotations=READ)
def meta_post_kit(creative_id: int):
    """O que o operador publica na Página para anunciar um criativo: título, texto, link com UTM e a imagem. Entregue no chat; ele publica."""
    return _run(lambda: _client.get(f"/ads/meta-post-kit/{creative_id}"))


@mcp.tool(annotations=READ)
def meta_page_posts(limit: int = 10):
    """Posts recentes publicados na Página (id, texto, link): ache o post que o operador publicou e use o id em `ad_create(post_id=...)`."""
    return _run(lambda: _client.get("/ads/page-posts", limit=max(1, min(int(limit), 25))))


@mcp.tool(annotations=WRITE)
def google_ad_create(product_id: int, daily_brl: float, days: int = 3, dry_run: bool = True, max_cpc_brl: float = 1.0,
                     keywords: list[str] | None = None, headlines: list[str] | None = None, descriptions: list[str] | None = None):
    """Cria a campanha de PESQUISA no Google Ads de um produto da vitrine. EXIGE o modo agente.

    `dry_run=True` (padrão) só mostra o plano (títulos, descrições, palavras-chave, link), sem tocar no Google: use sempre primeiro e mostre no
    chat. Com `dry_run=False` a campanha nasce PAUSADA (nada gasta); quem LIGA é o operador. A verba é o orçamento PRÓPRIO do Google (campos GOOGLE do
    cartão), separado do da Meta. Sem `keywords`/`headlines`/`descriptions` o sistema monta do produto. Regras do Google: título até 30
    caracteres e sem "!", descrição até 90, 3 a 15 títulos, 2 a 4 descrições; sem promessas que não possam ser provadas (grátis, garantido,
    melhor). Use `max_cpc_brl` baixo (padrão R$ 1). Anúncio de pesquisa pega quem já procura o produto: prefira produtos com demanda de busca.
    """
    body = {"product_id": product_id, "daily_brl": daily_brl, "days": days, "dry_run": dry_run, "max_cpc_brl": max_cpc_brl}
    for key, value in (("keywords", keywords), ("headlines", headlines), ("descriptions", descriptions)):
        if value:
            body[key] = value
    return _run(lambda: _client.post("/ads/google", body))


@mcp.tool(annotations=WRITE)
def ad_pause(ad_id: int):
    """Pausa um anúncio ativo (a decisão de pausar o que não rende é sua; a de ligar é do operador). EXIGE o modo agente."""
    return _run(lambda: _client.post(f"/ads/{ad_id}/pause"))


@mcp.tool(annotations=WRITE)
def ads_sync_metrics():
    """Lê da Meta e do Google gasto, impressões e cliques dos anúncios existentes e atualiza o painel. Faça antes de analisar desempenho. EXIGE o modo agente."""
    return _run(lambda: _client.post("/ads/sync"))


@mcp.tool(annotations=READ)
def goals_status():
    """As metas do mês definidas pelo operador e o quanto já foi feito (produtos na vitrine, posts, cliques, vendas, comissão).

    Mostra o realizado, o ritmo esperado até hoje, a projeção para o fim do mês e quais metas estão atrasadas.
    `periods` traz o ritmo de hoje, da semana, da quinzena e do mês (a meta mensal repartida pelos dias).
    Consulte no começo de cada rotina e priorize o que fecha as metas atrasadas. Você não altera as metas: elas são do operador.
    """
    return _run(lambda: _client.get("/agent/goals"))


@mcp.tool(annotations=READ)
def storefront_status():
    """A vitrine pública (loja Mural na Web): produtos, categoria, o que pode ser publicado e por quê, último envio.

    Todo item do portfólio entra na loja por padrão. Produto sem link de afiliado ou sem foto aparece com o motivo.
    """
    return _run(lambda: _client.get("/storefront"))


@mcp.tool(annotations=WRITE)
def storefront_update_item(product_id: int, category: str | None = None, blurb: str | None = None,
                           display_title: str | None = None, highlight: bool | None = None,
                           hidden: bool | None = None, position: int | None = None):
    """Ajusta como um produto aparece na loja pública. EXIGE o modo agente.

    `blurb`: uma frase honesta (até 280 caracteres) sobre por que vale a pena — sem promessa de resultado nem avaliação inventada.
    `display_title`: nome curto e claro no lugar do título cheio de palavras-chave do marketplace.
    `category`: Eletrônicos, Casa, Moda, Beleza, Games, Pet, Cursos ou Achados diversos. `highlight` destaca (bloco duplo).
    Só é publicado depois de `storefront_publish`.
    """
    return _run(lambda: _client.put(f"/storefront/items/{product_id}", {
        "category": category, "blurb": blurb, "display_title": display_title, "highlight": highlight,
        "hidden": hidden, "position": position}))


@mcp.tool(annotations=WRITE)
def storefront_publish():
    """Publica a vitrine: envia ao site público a lista atual de produtos. EXIGE o modo agente.

    Faça depois de mudar a lista ou os textos, e na rotina da manhã quando entrou produto novo. Cria os links curtos
    rastreados que faltam (canal vitrine) para contar os cliques da loja.
    """
    return _run(lambda: _client.post("/storefront/publish"))


@mcp.tool(annotations=READ)
def list_tracked_links(portfolio_item_id: int | None = None, product_id: int | None = None):
    """Links rastreados criados e quantos cliques cada um recebeu (por produto, canal e campanha)."""
    return _run(lambda: _client.get("/links", portfolio_item_id=portfolio_item_id, product_id=product_id))


@mcp.prompt(name="ativacao", description="Roda a rotina completa de ativação do agente no marketTon.")
def ativacao() -> str:
    return (
        "Execute a rotina de ativação do marketTon: leia `agent_playbook` e `chat_inbox`, rode `system_health`, "
        "`marketton_checklist` e `sync_sales`, analise o catálogo com `product_funnel`, escolha e vincule os produtos "
        "com mais chance de venda, poste um relatório no chat, peça com `request_resource` o que faltar e conclua a "
        "tarefa com `complete_task`."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
