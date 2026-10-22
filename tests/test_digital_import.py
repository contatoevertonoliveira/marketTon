"""Importação de produtos digitais por planilha e comissão da Monetizze (rota de afiliações)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.services import digital_import as di
from integrations.marketplaces.digital_platforms import MonetizzeAdapter

CSV = """plataforma;nome;link;comissao_pct;comissao_reais;preco;foto;categoria
Hotmart;Curso de Excel Completo;https://pay.hotmart.com/ABC123;40%;;R$ 197,00;https://img.exemplo.com/a.jpg;Cursos
eduzz;Mentoria de Vendas;https://sun.eduzz.com/XYZ;;R$ 120,50;1.297,00;;
monetizze;Sem link;ftp://x;;;;;
hotmart;;https://pay.hotmart.com/SEMNOME;;;;;
orkut;Outro;https://x.com/y;;;;;
"""


def test_valid_rows_are_imported_with_manual_provenance_and_bad_rows_are_listed(session):
    report = di.import_csv(session, CSV)
    assert report.created_or_updated == 2 and report.by_platform == {"hotmart": 1, "eduzz": 1} and len(report.errors) == 3
    assert any("https" in e for e in report.errors) and any("falta o nome" in e for e in report.errors) and any("orkut" in e for e in report.errors)
    hot = session.scalar(select(Product).where(Product.marketplace == Marketplace.HOTMART))
    assert hot.title == "Curso de Excel Completo" and hot.price == 197.0 and hot.affiliate_commission_pct == 40.0
    assert hot.affiliate_url == "https://pay.hotmart.com/ABC123" and hot.images == ["https://img.exemplo.com/a.jpg"]
    edu = session.scalar(select(Product).where(Product.marketplace == Marketplace.EDUZZ))
    assert edu.price == 1297.0 and edu.affiliate_commission_fixed == 120.5 and edu.affiliate_commission_pct is None  # nada inventado
    assert {s.connector_kind for s in session.scalars(select(SourceRecord))} == {ConnectorKind.MANUAL}


def test_reimporting_the_same_link_updates_instead_of_duplicating(session):
    di.import_csv(session, CSV)
    di.import_csv(session, CSV.replace("197,00", "147,00"))
    assert session.query(Product).filter(Product.marketplace == Marketplace.HOTMART).count() == 1
    assert session.scalar(select(Product.price).where(Product.marketplace == Marketplace.HOTMART)) == 147.0


def test_bad_sheets_are_rejected_clearly(session):
    with pytest.raises(di.ImportError_, match="vazia"):
        di.import_csv(session, "  ")
    with pytest.raises(di.ImportError_, match="faltam as colunas"):
        di.import_csv(session, "nome;preco\nX;1")
    with pytest.raises(di.ImportError_, match="nenhuma linha válida"):
        di.import_csv(session, "plataforma;nome;link\nhotmart;X;http://inseguro")
    assert session.query(Product).count() == 0


def test_numbers_accept_brazilian_and_international_formats():
    assert [di._num(v) for v in ("R$ 1.234,56", "12,5", "12.5", "12,5%", "", "abc", "1,234.50")] == [1234.56, 12.5, 12.5, 12.5, None, None, 1234.5]


def test_monetizze_commission_text_is_parsed_as_a_ceiling_or_a_percentage():
    parse = MonetizzeAdapter.parse_commission
    assert parse("Até R$ 141,42") == (141.42, None, True)
    assert parse("Até R$ 1.250,00") == (1250.0, None, True)
    assert parse("30%") == (None, 30.0, False)
    assert parse(None) == (None, None, False)
