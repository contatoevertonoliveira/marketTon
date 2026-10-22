"""Importação em lote de produtos digitais (Hotmart, Eduzz, Monetizze) a partir de uma planilha CSV.

Por que existe: essas plataformas não têm API para **descobrir** produtos de afiliação (o Mercado da Hotmart, a vitrine da
Eduzz e a da Monetizze só existem nos painéis). O operador escolhe no painel de cada uma e cola aqui o que viu; o marketTon
cadastra no catálogo com procedência `manual`, e daí em diante o produto é tratado como qualquer outro (funil, vitrine, agente).

Colunas (cabeçalho obrigatório; aceita vírgula ou ponto e vírgula; nomes em português ou inglês):

    plataforma, nome, link, comissao_pct, comissao_reais, preco, foto, categoria, id

Só `plataforma`, `nome` e `link` são obrigatórios. O link precisa ser https (é o seu link de afiliado). Nada é inventado:
coluna vazia fica sem dado.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.services.ingestion import ingest_products
from integrations.marketplaces.base import ConnectorBatch, ConnectorProduct

PLATFORMS = {"hotmart": Marketplace.HOTMART, "eduzz": Marketplace.EDUZZ, "monetizze": Marketplace.MONETIZZE}
ALIASES = {
    "plataforma": "plataforma", "platform": "plataforma", "marketplace": "plataforma",
    "nome": "nome", "name": "nome", "titulo": "nome", "título": "nome", "produto": "nome",
    "link": "link", "url": "link", "link_afiliado": "link", "link de afiliado": "link", "affiliate_url": "link",
    "comissao_pct": "comissao_pct", "comissao %": "comissao_pct", "comissão %": "comissao_pct", "comissao_percentual": "comissao_pct",
    "comissao_reais": "comissao_reais", "comissão r$": "comissao_reais", "comissao r$": "comissao_reais", "comissao": "comissao_reais",
    "preco": "preco", "preço": "preco", "price": "preco",
    "foto": "foto", "imagem": "foto", "image": "foto",
    "categoria": "categoria", "category": "categoria",
    "id": "id", "codigo": "id", "código": "id",
}
MAX_ROWS = 300


class ImportError_(ValueError):
    """Planilha inválida; a mensagem é segura para exibir."""


@dataclass
class ImportReport:
    created_or_updated: int = 0
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    by_platform: dict[str, int] = field(default_factory=dict)


def _num(value: str | None) -> float | None:
    """Número no formato brasileiro ou internacional: 'R$ 1.234,56', '12,5', '12.5', '12,5%'."""
    text = re.sub(r"[^\d,.\-]", "", (value or "").strip())
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_rows(text: str) -> list[dict]:
    text = (text or "").lstrip("﻿").strip()
    if not text:
        raise ImportError_("a planilha está vazia")
    sample = text.splitlines()[0]
    delimiter = ";" if sample.count(";") > sample.count(",") else ("\t" if sample.count("\t") > sample.count(",") else ",")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportError_("a planilha está vazia") from exc
    columns = [ALIASES.get(h.strip().lower()) for h in header]
    missing = {"plataforma", "nome", "link"} - set(c for c in columns if c)
    if missing:
        raise ImportError_(f"faltam as colunas obrigatórias: {', '.join(sorted(missing))}. Cabeçalho lido: {', '.join(h.strip() for h in header)}")
    rows = []
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        rows.append({col: (raw[i].strip() if i < len(raw) else "") for i, col in enumerate(columns) if col})
        if len(rows) > MAX_ROWS:
            raise ImportError_(f"planilha grande demais (máximo {MAX_ROWS} linhas por importação)")
    return rows


def _product(row: dict, line: int) -> tuple[Marketplace, ConnectorProduct]:
    platform = PLATFORMS.get(re.sub(r"[^a-z]", "", row.get("plataforma", "").lower()))
    if platform is None:
        raise ImportError_(f"linha {line}: plataforma desconhecida “{row.get('plataforma', '')}” (use hotmart, eduzz ou monetizze)")
    name = re.sub(r"\s+", " ", row.get("nome", "")).strip()
    if not name:
        raise ImportError_(f"linha {line}: falta o nome")
    link = row.get("link", "").strip()
    if not link.startswith("https://") or " " in link:
        raise ImportError_(f"linha {line}: o link precisa ser um endereço https (seu link de afiliado)")
    pct, reais = _num(row.get("comissao_pct")), _num(row.get("comissao_reais"))
    if pct is not None and pct > 100:
        raise ImportError_(f"linha {line}: comissão em % acima de 100")
    price = _num(row.get("preco"))
    image = row.get("foto", "").strip()
    external_id = row.get("id", "").strip() or "m-" + hashlib.sha1(link.encode()).hexdigest()[:14]
    return platform, ConnectorProduct(
        external_id=external_id[:128], title=name[:300], currency="BRL", price=price, is_available=True,
        affiliate_commission_pct=pct, affiliate_commission_fixed=reais, affiliate_url=link, product_url=link,
        images=[image] if image.startswith("https://") else None,
        attributes={"platform": platform.value, "imported_manually": True, "category_hint": row.get("categoria") or None},
    )


def import_csv(session: Session, text: str) -> ImportReport:
    """Importa a planilha. Linhas inválidas são puladas e listadas; nada é gravado se nenhuma linha servir."""
    report = ImportReport()
    batches: dict[Marketplace, list[ConnectorProduct]] = {}
    for line, row in enumerate(parse_rows(text), start=2):
        report.rows += 1
        try:
            platform, product = _product(row, line)
        except ImportError_ as exc:
            report.errors.append(str(exc))
            continue
        batches.setdefault(platform, []).append(product)
    if not batches:
        raise ImportError_("nenhuma linha válida. " + (report.errors[0] if report.errors else ""))
    now = datetime.now(UTC)
    for platform, products in batches.items():
        batch = ConnectorBatch(connector="manual_import", products=products, collected_at=now, reliability=0.7,
                               endpoint="importação por planilha (escolhida pelo operador no painel da plataforma)",
                               warnings=["Dados digitados pelo operador a partir do painel da plataforma; não verificados por API."])
        # Sem preço, o item não tem sinal de mercado: aqui ele vale mesmo assim (o operador o escolheu).
        ingest_products(session, batch, platform, observed_at=now, skip_without_market_signal=False)
        report.by_platform[platform.value] = len(products)
        report.created_or_updated += len(products)
    return report
