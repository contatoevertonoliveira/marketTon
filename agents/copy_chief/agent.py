"""Copy Chief agent runtime — direct, weekly-ready, Lobos-style + MCP."""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult
from agents.core.mcp_state import MCPState

OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "copy_variants.csv"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# direct, non-gourmetized copy aligned to Lobos: headline obvious + parcelamento anchor
DIRECT_TEMPLATES = [
    '{product}: solução direta. Aproveite agora.',
    'Mais pedidos de {product} esta semana. Garanta o seu.',
    '{product}: simples, prático e para quem quer resultado rápido.',
    'Quem testou {product} repete. Veja por que está em alta.',
    'Preço acessível em {product}. Apenas comece.',
]
DIRECT_HEADLINES = [
    'Oferta direta',
    'Mais pedidos da semana',
    'Quem testou repete',
    'Promoção simples',
    'Comece agora',
]
CASE_TEMPLATES = [
    'Case: {case_title} usando {product}.',
    'Resultado real com {product}: {case_title}.',
]
CASE_HEADLINES = [
    'Caso real',
    'Estudo de caso',
    'Quem aplicou, aprovou',
]


def run(memory: Memory) -> TaskResult:
    mcp = MCPState()
    method = mcp.methodology
    products_path = memory.get("product_hunter_path") or str(
        Path(__file__).resolve().parent.parent.parent / "data" / "products" / "product_hunter_latest.csv"
    )
    try:
        products = pd.read_csv(products_path)
    except Exception:
        products = pd.DataFrame()
    rows: list[dict] = []

    if not products.empty and method.get("must_have_case") is False:
        candidates = products.head(8)
        for _, item in candidates.iterrows():
            title = str(item.get("title") or item.get("name") or item.get("product") or "Produto")
            for i in range(3):
                rows.append(
                    {
                        "product": title,
                        "headline": random.choice(DIRECT_HEADLINES),
                        "body": random.choice(DIRECT_TEMPLATES).format(product=title),
                        "style": "direct",
                        "version": i + 1,
                        "generated_at": datetime.now().isoformat(),
                    }
                )

    family = _next_case_family() if method.get("must_have_case") else None
    if family:
        rows.extend(
            [
                {
                    "product": "Negócio de 4 Rend",
                    "headline": random.choice(CASE_HEADLINES),
                    "body": f"Case: {family} usando Negócio de 4 Rend.",
                    "style": "case_social_proof",
                    "version": 1,
                    "generated_at": datetime.now().isoformat(),
                }
                for _ in range(4)
            ]
        )

    df = pd.DataFrame(rows or [{"product": "placeholder", "headline": "—", "body": "Sem copy."}])
    df.to_csv(OUTPUT, index=False, mode="w")
    mcp.update_ctx(last_copy_batch={"rows": int(len(df)), "ts": datetime.now().isoformat()})
    mcp.enqueue("copy_pending", {"rows": int(len(df)), "ts": datetime.now().isoformat()})
    return TaskResult(
        task_id="copy_chief",
        ok=True,
        summary=f"generated {len(df)} direct copy variants for weekly flow",
        artifacts={"path": str(OUTPUT), "rows": int(len(df)), "family": family},
    )


def _next_case_family() -> str:
    # simple rotating selection for case-based conversion
    opts = [
        "jovem iniciante",
        "mãe de família",
        "ex-CLT",
        "trabalhador de feira",
        "pessoa comum sem experiência",
    ]
    return random.choice(opts)
