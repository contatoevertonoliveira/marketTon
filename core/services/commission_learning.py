"""Aprende a comissão real de um produto a partir das vendas dele.

Muitos produtos chegam sem comissão informada (a API do marketplace não expõe, ou
só devolve uma taxa que não é a que vale no canal em que o operador divulga).
Depois que o produto vende, o marketplace informa a comissão paga/estimada de cada
venda — então a taxa efetiva pode ser **observada**, não adivinhada:

    taxa = soma das comissões das vendas / soma dos valores vendidos

Regras (todas visíveis na proposta):

* só preenche produto **sem** comissão ou com comissão **aprendida antes** deste
  jeito (marca em `attributes.commission_source`); nunca sobrescreve valor vindo da
  API, da tabela do operador ou digitado à mão;
* vendas canceladas não entram; comissão confirmada vale mais que a estimada;
* poucas vendas = confiança baixa, e isso aparece (`confidence`);
* a taxa é observada no canal em que as vendas aconteceram (ex.: Shopee Vídeo),
  que pode diferir da taxa anunciada — por isso o rótulo é "observada nas vendas".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.base import Marketplace
from core.db.catalog import Product
from core.db.tracking import Commission, Sale

SOURCE = "observed_from_sales"
LEARNED_KEYS = ("commission_source", "commission_sample_sales", "commission_learned_at", "commission_basis")


@dataclass
class CommissionProposal:
    product_id: int
    marketplace: str
    title: str
    current_pct: float | None
    proposed_pct: float
    sales_count: int
    gross_total: float
    commission_total: float
    basis: str  # "confirmed" | "mixed" | "estimated"
    confidence: str  # "alta" | "media" | "baixa"
    applied: bool = False

    @property
    def changed(self) -> bool:
        return self.current_pct is None or abs(self.current_pct - self.proposed_pct) >= 0.05


def _confidence(sales_count: int) -> str:
    return "alta" if sales_count >= 5 else "media" if sales_count >= 2 else "baixa"


def propose_commissions(
    session: Session, *, marketplace: Marketplace | None = None, min_sales: int = 1
) -> list[CommissionProposal]:
    """Calcula a taxa observada de cada produto elegível. Não grava nada."""
    stmt = select(Sale, Commission).join(Commission, Commission.sale_id == Sale.id).where(Sale.product_id.is_not(None))
    if marketplace is not None:
        stmt = stmt.where(Sale.marketplace == marketplace)

    agg: dict[int, dict] = {}
    for sale, commission in session.execute(stmt):
        if (sale.status or "").upper() == "CANCELLED" or not sale.gross_amount or sale.gross_amount <= 0:
            continue
        confirmed = commission.status == "confirmed" and commission.confirmed_amount is not None
        amount = commission.confirmed_amount if confirmed else commission.estimated_amount
        if amount is None:
            continue
        bucket = agg.setdefault(sale.product_id, {"gross": 0.0, "commission": 0.0, "n": 0, "confirmed": 0})
        bucket["gross"] += float(sale.gross_amount)
        bucket["commission"] += float(amount)
        bucket["n"] += 1
        bucket["confirmed"] += 1 if confirmed else 0

    proposals: list[CommissionProposal] = []
    for product_id, b in agg.items():
        if b["n"] < min_sales or b["gross"] <= 0:
            continue
        product = session.get(Product, product_id)
        if product is None:
            continue
        learned_before = (product.attributes or {}).get("commission_source") == SOURCE
        if product.affiliate_commission_pct is not None and not learned_before:
            continue  # valor da API, do operador ou digitado: não se mexe
        rate = round(b["commission"] / b["gross"] * 100, 2)
        basis = "confirmed" if b["confirmed"] == b["n"] else "estimated" if b["confirmed"] == 0 else "mixed"
        proposal = CommissionProposal(
            product_id=product.id,
            marketplace=product.marketplace.value,
            title=product.title,
            current_pct=product.affiliate_commission_pct,
            proposed_pct=rate,
            sales_count=b["n"],
            gross_total=round(b["gross"], 2),
            commission_total=round(b["commission"], 2),
            basis=basis,
            confidence=_confidence(b["n"]),
        )
        if proposal.changed:
            proposals.append(proposal)
    return sorted(proposals, key=lambda p: -p.sales_count)


def apply_commissions(session: Session, proposals: list[CommissionProposal]) -> int:
    """Grava as propostas e marca a procedência no produto. Devolve quantas aplicou."""
    now = datetime.now(UTC).isoformat()
    applied = 0
    for proposal in proposals:
        product = session.get(Product, proposal.product_id)
        if product is None:
            continue
        product.affiliate_commission_pct = proposal.proposed_pct
        product.attributes = {
            **(product.attributes or {}),
            "commission_source": SOURCE,
            "commission_sample_sales": proposal.sales_count,
            "commission_learned_at": now,
            "commission_basis": proposal.basis,
        }
        proposal.applied = True
        applied += 1
    session.flush()
    return applied


__all__ = ["CommissionProposal", "LEARNED_KEYS", "SOURCE", "apply_commissions", "propose_commissions"]
