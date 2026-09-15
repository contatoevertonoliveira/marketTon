"""Configuração central da aplicação, carregada de variáveis de ambiente."""
from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração validada. Falha no start se algo obrigatório estiver ausente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicação ------------------------------------------------------------
    app_name: str = "marketTon — Affiliate Intelligence System"
    app_version: str = "0.3.0"
    debug: bool = False

    # --- Banco de dados -------------------------------------------------------
    database_url: str = "postgresql+psycopg://marketton:marketton@localhost:5432/marketton"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True
    # Testes unitários podem rodar em SQLite por velocidade. Em desenvolvimento,
    # produção e no docker compose o banco é sempre PostgreSQL.
    allow_sqlite: bool = False

    # --- Cache / fila ---------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- API ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    # Mantido como string de propósito: um campo `list[str]` faz o pydantic-settings
    # tentar `json.loads` no valor da variável de ambiente ANTES de qualquer
    # validador, o que quebraria o formato documentado `CORS_ORIGINS=a,b`.
    # Use `cors_origin_list` para obter a lista.
    cors_origins: str = "http://localhost:5173"

    # --- Camada de IA ---------------------------------------------------------
    # Desligada por padrão: o sistema precisa ser auditável sem LLM.
    ai_enabled: bool = False
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2

    # --- Autenticação ---------------------------------------------------------
    # Segredo de desenvolvimento. Em produção DEVE ser substituído: um segredo
    # conhecido permite forjar token de admin. `is_using_dev_secret` existe para
    # que a aplicação possa avisar em vez de falhar em silêncio.
    jwt_secret_key: str = "dev-only-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12
    # Custo do Argon2. Argon2 é intencionalmente lento e memory-hard — é o que o
    # torna resistente a ataque com GPU. Os padrões abaixo são o recomendado da
    # RFC 9106 (segunda opção). A suíte de testes reduz o custo: gerar centenas de
    # hashes com o custo de produção domina o tempo de execução sem acrescentar
    # cobertura.
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    # Desligar auth só é aceitável em desenvolvimento local. Em produção a API
    # precisa recusar subir sem segredo configurado.
    auth_enabled: bool = True
    # Cria o primeiro admin automaticamente no start, quando não há usuário nenhum.
    # Existe para permitir o bootstrap; depois disso, usuários são criados pela API.
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""

    # --- Coleta ---------------------------------------------------------------
    agent_cycle_interval_seconds: int = 3600
    connector_timeout_seconds: float = 20.0

    # --- Meta Ads (Marketing API / Ads Library) --------------------------------
    meta_access_token: str = ""
    meta_ad_account_id: str = ""

    # --- Mercado Livre --------------------------------------------------------
    # https://developers.mercadolivre.com.br/ — app do tipo "Server Side".
    mercadolivre_client_id: str = ""
    mercadolivre_client_secret: str = ""
    mercadolivre_redirect_uri: str = "http://localhost:8000/marketplaces/mercadolivre/callback"
    mercadolivre_access_token: str = ""
    mercadolivre_refresh_token: str = ""
    mercadolivre_site_id: str = "MLB"
    mercadolivre_country: str = "BR"

    # --- Shopee ---------------------------------------------------------------
    # https://open.shopee.com/ — a API de afiliado exige aprovação de parceiro.
    shopee_partner_id: str = ""
    shopee_partner_key: str = ""
    shopee_access_token: str = ""
    shopee_refresh_token: str = ""
    shopee_shop_id: str = ""

    # --- Amazon ---------------------------------------------------------------
    # https://webservices.amazon.com/paapi5/documentation/ — SigV4.
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    amazon_region: str = "us-east-1"
    amazon_host: str = "webservices.amazon.com.br"
    amazon_marketplace: str = "www.amazon.com.br"

    # --- TikTok Shop ----------------------------------------------------------
    # https://partner.tiktokshop.com/ — Affiliate Open API.
    tiktokshop_app_key: str = ""
    tiktokshop_app_secret: str = ""
    tiktokshop_access_token: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _normalize_origins(cls, value: object) -> object:
        """Aceita lista Python e também o formato serializado `["a","b"]`."""
        if isinstance(value, (list, tuple)):
            return ",".join(str(item).strip() for item in value if str(item).strip())
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        """Origens liberadas no CORS, já separadas e sem espaços."""
        raw = self.cors_origins.strip()
        if raw.startswith("["):
            try:
                import json

                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(origin).strip() for origin in parsed if str(origin).strip()]
            except ValueError:
                pass
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_ai_configured(self) -> bool:
        return self.ai_enabled and bool(self.ai_api_key)

    @property
    def is_using_dev_secret(self) -> bool:
        """True enquanto o segredo JWT for o de desenvolvimento.

        Não é erro fatal — o sistema precisa subir em desenvolvimento. Mas precisa
        ser visível: um segredo conhecido permite forjar token de administrador.
        """
        return self.jwt_secret_key == "dev-only-insecure-change-me"

    def validate_production_readiness(self) -> list[str]:
        """Problemas que impedem uso em produção. Devolve a lista, não levanta.

        Devolver a lista permite que o `/health` mostre todos os problemas de uma
        vez, em vez de o operador descobrir um por reinício.
        """
        problems: list[str] = []
        if not self.auth_enabled:
            problems.append("AUTH_ENABLED=false: a API está sem autenticação")
        if self.is_using_dev_secret:
            problems.append(
                "JWT_SECRET_KEY ainda é o valor de desenvolvimento; "
                "gerei/defina um segredo próprio antes de expor a API"
            )
        if self.is_sqlite:
            problems.append("DATABASE_URL aponta para SQLite")
        if not self.is_ai_configured:
            problems.append("IA desligada: agentes operam sem interpretação")
        return problems

    def validate_database_url(self) -> None:
        """Rejeita SQLite fora do modo de teste.

        O domínio depende de concorrência entre API e workers e de tipos que o
        SQLite não oferece; permiti-lo em desenvolvimento foi o que produziu três
        schemas divergentes. `ALLOW_SQLITE=true` existe apenas para os testes.
        """
        if self.is_sqlite and not self.allow_sqlite:
            raise ValueError(
                "DATABASE_URL aponta para SQLite. Use PostgreSQL "
                "(docker compose up -d db). Para testes unitários, defina ALLOW_SQLITE=true."
            )


@lru_cache
def get_settings() -> Settings:
    """Instância única. Use `get_settings.cache_clear()` em testes."""
    return Settings()
