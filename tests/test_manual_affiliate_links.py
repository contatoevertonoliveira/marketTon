"""Links de afiliado colados à mão (Mercado Livre): só endereços do próprio marketplace, achar o produto pelo código MLB e não apagar na coleta."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.db  # noqa: F401
from core.db import Base
from core.db.base import ConnectorKind, Marketplace
from core.db.catalog import Product, SourceRecord
from core.services import manual_affiliate_links as mal

NOW = datetime.now(UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _ml(session, ext="MLB1234567890", url="https://produto.mercadolivre.com.br/MLB-1234567890-serra-circular-_JM"):
    src = SourceRecord(marketplace=Marketplace.MERCADO_LIVRE, connector="ml", connector_kind=ConnectorKind.OFFICIAL_API, endpoint="x", external_id=ext, collected_at=NOW)
    session.add(src)
    session.flush()
    p = Product(marketplace=Marketplace.MERCADO_LIVRE, external_id=ext, title="Serra circular", price=500.0, product_url=url, source_record_id=src.id,
                first_seen_at=NOW, last_seen_at=NOW)
    session.add(p)
    session.flush()
    return p


def test_only_the_marketplaces_own_link_addresses_are_accepted():
    assert mal.validate_link("mercado_livre", "https://mercadolivre.com/sec/2abcDe") == "https://mercadolivre.com/sec/2abcDe"
    assert mal.validate_link("mercado_livre", "https://meli.la/1AbC")
    for bad in ("http://mercadolivre.com/sec/x", "https://evil.com/mercadolivre.com", "https://mercadolivre.com.evil.com/x", "javascript:alert(1)"):
        with pytest.raises(mal.AffiliateLinkError):
            mal.validate_link("mercado_livre", bad)
    with pytest.raises(mal.AffiliateLinkError, match="vem da API"):
        mal.validate_link("shopee", "https://s.shopee.com.br/x")  # Shopee tem API: não se cola à mão


def test_import_matches_the_product_by_its_mlb_code_and_reports_what_it_could_not_do(session):
    p = _ml(session)
    text = ("# produto  link\n"
            "https://produto.mercadolivre.com.br/MLB-1234567890-serra-circular-_JM?x=1  https://mercadolivre.com/sec/2abcDe\n"
            "https://produto.mercadolivre.com.br/MLB-9999999999-outro-_JM;https://mercadolivre.com/sec/9\n"
            "https://produto.mercadolivre.com.br/MLB-1234567890-serra  https://site-falso.com/x\n"
            "linha com uma coluna só\n")
    out = mal.import_links(session, text)
    assert [s["product_id"] for s in out["saved"]] == [p.id] and p.affiliate_url == "https://mercadolivre.com/sec/2abcDe"
    assert len(out["not_in_catalog"]) == 1 and len(out["rejected"]) == 2


def test_a_manual_link_survives_a_catalog_refresh_that_brings_none(session):
    from core.services.ingestion import _apply_product_fields
    from types import SimpleNamespace
    p = _ml(session)
    mal.set_affiliate_url(session, p.id, "https://meli.la/1AbC")
    item = SimpleNamespace(**{f: None for f in ("title", "category_id", "category_path", "brand", "model", "condition", "currency", "price", "original_price", "discount_pct",
                                                "affiliate_commission_pct", "affiliate_commission_fixed", "available_quantity", "sold_quantity", "is_available", "rating",
                                                "review_count", "ranking_position", "popularity_score", "has_promotion", "coupons", "product_url", "affiliate_url", "images",
                                                "attributes")})
    item.price = 480.0
    _apply_product_fields(p, item)
    assert p.price == 480.0 and p.affiliate_url == "https://meli.la/1AbC"
