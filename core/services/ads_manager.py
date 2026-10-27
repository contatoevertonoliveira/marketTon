"""Operar anúncios de qualquer rede (Meta, Google) pelo mesmo caminho: ligar, pausar, parada geral e leitura de métricas.

Cada função escolhe a rede pela plataforma do anúncio. Uma rede fora do ar ou não configurada não impede a outra.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from core.db.ads import AdCampaign
from core.services import google_campaigns, meta_campaigns
from core.services.meta_campaigns import AdsError

logger = logging.getLogger(__name__)


def _module(session: Session, ad_id: int):
    ad = session.get(AdCampaign, ad_id)
    if ad is None:
        raise AdsError(f"anúncio {ad_id} não encontrado")
    return google_campaigns if ad.platform == "google" else meta_campaigns


def activate(session: Session, ad_id: int, *, actor: str, now: datetime | None = None) -> AdCampaign:
    return _module(session, ad_id).activate(session, ad_id, actor=actor, now=now)


def pause(session: Session, ad_id: int) -> AdCampaign:
    return _module(session, ad_id).pause(session, ad_id)


def pause_all(session: Session) -> int:
    return meta_campaigns.pause_all(session) + google_campaigns.pause_all(session)


def sync_metrics(session: Session, now: datetime | None = None) -> int:
    """Lê as métricas de todas as redes. Se uma falhar e a outra não, devolve o que foi lido; se todas falharem, levanta o erro."""
    done, errors = 0, []
    for name, module in (("Meta", meta_campaigns), ("Google", google_campaigns)):
        try:
            done += module.sync_metrics(session, now)
        except AdsError as exc:
            logger.info("métricas do %s indisponíveis: %s", name, exc)
            errors.append(f"{name}: {exc}")
    if errors and done == 0 and len(errors) == 2:
        raise AdsError("; ".join(errors))
    return done
