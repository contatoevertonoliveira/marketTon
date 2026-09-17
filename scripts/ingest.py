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

Uso:
    python scripts/ingest.py --marketplace mercado_livre
    python scripts/ingest.py --marketplace all --keywords "fone bluetooth,tenis running"
    python scripts/ingest.py --marketplace shopee --limit 20 --no-ai
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


if __name__ == "__main__":
    raise SystemExit(main())
