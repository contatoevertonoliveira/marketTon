"""Mercado Livre OAuth2 login flow (Fase 2).

Ported from the legacy FastAPI backend's `/market/ml/auth-url` and
`/market/ml/token` endpoints (backend/main.py), which existed but were never
wired into the new Django backend — that gap is what this module closes.
Reuses `integrations/marketplaces/mercado_livre.py` as-is for the actual
HTTP calls; this module only handles credential persistence + the redirect
dance.
"""
from __future__ import annotations

import secrets

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Marketplace, MarketplaceCredential


def _ml_adapter(cred: MarketplaceCredential):
    from integrations.marketplaces.mercado_livre import MercadoLivreAdapter, MLConfig

    cfg = MLConfig(
        client_id=cred.values.get("client_id", ""),
        client_secret=cred.values.get("client_secret", ""),
        redirect_uri=cred.values.get("redirect_uri", ""),
    )
    return MercadoLivreAdapter(cfg)


def _page(message: str) -> str:
    return (
        "<html><body style='font-family:sans-serif;padding:40px;max-width:480px'>"
        f"<h3>{message}</h3></body></html>"
    )


class MercadoLivreOAuthStartView(APIView):
    def post(self, request):
        marketplace, _ = Marketplace.objects.get_or_create(
            slug="mercado_livre", defaults={"name": "Mercado Livre", "integration_status": "live"}
        )
        cred, _ = MarketplaceCredential.objects.get_or_create(marketplace=marketplace)
        if not cred.values.get("client_id") or not cred.values.get("redirect_uri"):
            return Response(
                {"ok": False, "error": "configure client_id e redirect_uri em Integrações primeiro"}, status=400
            )
        state = secrets.token_urlsafe(16)
        cred.values["_oauth_state"] = state
        cred.save(update_fields=["values", "updated_at"])
        url = _ml_adapter(cred).build_authorization_url(state)
        return Response({"ok": True, "url": url, "redirect_uri": cred.values.get("redirect_uri")})


class MercadoLivreOAuthCallbackView(APIView):
    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        marketplace = Marketplace.objects.filter(slug="mercado_livre").first()
        cred = getattr(marketplace, "credential", None) if marketplace else None

        if not code or cred is None:
            return HttpResponse(_page("Falha: código ausente ou Mercado Livre ainda não configurado."), status=400)
        if not state or state != cred.values.get("_oauth_state"):
            return HttpResponse(_page("Falha: state inválido (link expirado ou reutilizado)."), status=400)

        token_data = _ml_adapter(cred).exchange_code_for_token(code)
        if not token_data:
            return HttpResponse(
                _page("Falha ao trocar o código por token. Confira client_id/client_secret/redirect_uri."),
                status=400,
            )

        cred.values["access_token"] = token_data.get("access_token", "")
        cred.values["refresh_token"] = token_data.get("refresh_token", "")
        cred.values.pop("_oauth_state", None)
        cred.save(update_fields=["values", "updated_at"])
        return HttpResponse(_page("Conectado com sucesso! Pode fechar esta aba e voltar ao painel."))
