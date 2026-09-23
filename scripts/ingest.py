#!/usr/bin/env python3
"""Dispara uma coleta real, sem depender do orquestrador de agentes.

Por que isto existe: `core.services.ingestion.ingest_products` só era chamado a
partir de `agents/product_hunter/agent.py`, que só roda através do
orquestrador — e o orquestrador não tem nenhum jeito exposto de ser iniciado
(sem endpoint de API, sem script de linha de comando) e ainda carrega um bug
conhecido no `enqueue()`. Configurar credenciais em Integrações não bastava:
não havia caminho nenhum, funcionando, para de fato puxar produtos.

Este script chama o mesmo pipeline que o agente chamaria
(`agents.product_hunter.agent.run`) diretamente contra uma sessão real do
Postgres, com os adapters já carregados com as credenciais salvas em
`marketplace_credentials` (a mesma sobreposição que a API usa em
`backend/deps.py::get_adapters`). Não fabrica dado: um marketplace sem
credencial configurada aparece como "sem credencial" no resumo, não como
catálogo vazio.

`--sales` chama o mesmo tipo de ponte, mas para `fetch_sales` ->
`core.services.sales_ingestion.ingest_sales`: nenhum adapter tinha
`fetch_sales` implementado de verdade até a Shopee ganhar um (via
`conversionReport`), e as tabelas `sales`/`commissions` nunca tinham sido
escritas por ninguém.

Uso:
    python scripts/ingest.py --marketplace mercado_livre
    python scripts/ingest.py --marketplace all --keywords "fone bluetooth,tenis running"
    python scripts/ingest.py --marketplace shopee --limit 20 --no-ai
    python scripts/ingest.py --marketplace shopee --sales
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.product_hunter.agent import DEFAULT_KEYWORDS, HunterOptions, run  # noqa: E402
from backend.deps import get_adapters  # noqa: E402
from core.db.session import session_scope  # noqa: E402
from core.services.sales_ingestion import ingest_sales  # noqa: E402
from integrations.marketplaces.registry import list_adapter_names, load_adapters  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispara ingestão real de produtos.")
    parser.add_argument(
        "--marketplace",
        default="all",
        help="nome do adapter (ex.: mercado_livre, shopee, amazon, tiktok_shop) ou 'all'",
    )
    parser.add_argument(
        "--keywords",
        default=None,
        help="palavras-chave separadas por vírgula (padrão: lista embutida do product_hunter)",
    )
    parser.add_argument("--limit", type=int, default=50, help="máx. itens coletados por adapter")
    parser.add_argument("--score-limit", type=int, default=25, help="máx. produtos pontuados")
    parser.add_argument("--no-ai", action="store_true", help="pula a avaliação qualitativa por IA")
    parser.add_argument("--json", action="store_true", help="imprime o resultado completo em JSON")
    parser.add_argument(
        "--sales",
        action="store_true",
        help="ingere vendas/comissão (fetch_sales) em vez de descobrir produtos",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="janela de vendas em dias, usado só com --sales (padrão: 30)",
    )
    args = parser.parse_args()

    load_adapters()
    available = list_adapter_names()

    if args.marketplace == "all":
        adapter_names = available
    else:
        if args.marketplace not in available:
            print(
                f"marketplace '{args.marketplace}' não registrado. Disponíveis: {', '.join(available)}",
                file=sys.stderr,
            )
            return 1
        adapter_names = [args.marketplace]

    if args.sales:
        return _run_sales(adapter_names, args)

    options = HunterOptions(
        keywords=[k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else list(DEFAULT_KEYWORDS),
        adapter_names=adapter_names,
        max_items_per_adapter=args.limit,
        score_limit=args.score_limit,
        use_ai=not args.no_ai,
    )

    adapters = get_adapters()

    with session_scope() as session:
        result = run({}, session=session, adapters=adapters, options=options)

    if args.json:
        print(json.dumps(result.artifacts, ensure_ascii=False, indent=2, default=str))
    else:
        print(result.summary)
        for error in result.artifacts.get("collect_errors", []):
            print(f"  - {error}")
        for warning in result.artifacts.get("collect_warnings", []):
            print(f"  (aviso) {warning}")

    return 0 if result.ok else 1


def _run_sales(adapter_names: list[str], args: argparse.Namespace) -> int:
    from datetime import UTC, datetime, timedelta

    adapters = get_adapters()
    since = datetime.now(UTC) - timedelta(days=args.since_days)
    exit_code = 0

    with session_scope() as session:
        for name in adapter_names:
            adapter = adapters.get(name)
            if adapter is None:
                print(f"adapter '{name}' não registrado", file=sys.stderr)
                exit_code = 1
                continue
            if not adapter.is_configured():
                print(f"adapter '{name}' sem credencial configurada; não coletou vendas")
                continue
            try:
                records = adapter.fetch_sales(since=since)
            except Exception as exc:  # noqa: BLE001 - reportar e seguir pro próximo marketplace
                print(f"adapter '{name}' falhou ao buscar vendas: {exc}", file=sys.stderr)
                exit_code = 1
                continue

            stats = ingest_sales(session, records, name)
            if args.json:
                print(json.dumps(stats.__dict__, ensure_ascii=False, indent=2, default=str))
            else:
                print(stats.summary())
                for warning in stats.warnings[:10]:
                    print(f"  (aviso) {warning}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
