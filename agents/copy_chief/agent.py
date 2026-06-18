"""Copy Chief agent runtime."""
from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.orchestrator import Memory
from core.tasks import TaskResult

OUTPUT = Path(__file__).resolve().parent.parent.parent / "data" / "copy_variants.csv"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

TEMPLATES = [
    '🔥 {title}: oferta por tempo limitado! Compre agora antes de acabar.',
    'Mais pedidos de {title} esta semana. Estoque baixando — garanta o seu.',
    'Quem testou {title} repete. Veja por que esse produto está em alta.',
    'Descontos especiais em {title}. Aproveite antes do preço subir.',
]

HEADLINES = [
    'Oferta relâmpago',
    'Estoque limitado',
    'Mais vendido da semana',
    'Promoção exclusiva',
]


def run(memory: Memory) -> TaskResult:
    products_path = memory.get("product_hunter_path") or str(
        Path(__file__).resolve().parent.parent.parent / "data" / "products" / "product_hunter_latest.csv"
    )
    rows: list[dict] = []
    try:
        products = pd.read_csv(products_path)
    except Exception as e:  # noqa: BLE001
        products = pd.DataFrame()
    if products.empty:
        return TaskResult(
            task_id="copy_chief",
            ok=True,
            summary="no products to base copy on",
            artifacts={"path": str(OUTPUT), "rows": 0},
        )
    candidates = products.head(10)
    for _, item in candidates.iterrows():
        title = str(item.get("title") or item.get("name") or item.get("product") or "Produto")
        for i in range(3):
            headlines = random.sample(HEADLINES, 1)[0]
            template = random.choice(TEMPLATES)
            body = template.format(title=title)
            rows.append(
                {
                    "product": title,
                    "headline": headlines,
                    "body": body,
                    "style": random.choice(["urgency", "social_proof", "direct"]),
                    "version": i + 1,
                    "generated_at": datetime.now().isoformat(),
                }
            )
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT, index=False, mode="w")
    return TaskResult(
        task_id="copy_chief",
        ok=True,
        summary=f"generated {len(df)} copy variants for {candidates.shape[0]} products",
        artifacts={"path": str(OUTPUT), "rows": int(len(df))},
    )
