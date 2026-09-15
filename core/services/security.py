"""Primitivas de segurança: hashing de senha e tokens JWT.

Decisões que valem registro:

**Argon2 via `pwdlib`.** `passlib` não recebe atualização desde 2020 e tem
incompatibilidade conhecida com `bcrypt` 4.x. `pwdlib` é o sucessor recomendado e
traz Argon2, que é resistente a GPU por ser memory-hard — diferente de SHA-256, que
seria inaceitável para senha.

**Access token curto + refresh token com estado.** Um JWT puro não pode ser
revogado antes de expirar. Por isso o access token dura horas e o refresh é
guardado no banco **como hash**: um vazamento do banco permite revogar os tokens,
não usá-los.

**Segredo de desenvolvimento é detectável.** `is_using_dev_secret` permite que a API
avise em vez de operar em silêncio com um segredo conhecido.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from config.settings import Settings, get_settings

# Algoritmo do JWT. HS256 é simétrico e adequado a um serviço único; um sistema
# com múltiplos verificadores independentes deveria usar RS256.
ALGORITHM = "HS256"

# Hasher construído sob demanda a partir da configuração. Criar o hasher a cada
# chamada recomputaria os parâmetros de custo, então ele é memoizado.
_hasher: PasswordHash | None = None
_hasher_cost: tuple[int, int, int] | None = None


def _build_hasher(settings: Settings) -> PasswordHash:
    """Hasher Argon2 com o custo vindo da configuração.

    O custo é configurável porque Argon2 é **intencionalmente** lento e
    memory-hard — é o que o torna resistente a GPU. Em produção ele deve ficar
    alto; na suíte de testes, onde centenas de hashes são gerados, o custo alto
    domina o tempo de execução sem acrescentar cobertura.
    """
    from pwdlib.hashers.argon2 import Argon2Hasher

    return PasswordHash(
        (
            Argon2Hasher(
                time_cost=settings.argon2_time_cost,
                memory_cost=settings.argon2_memory_cost,
                parallelism=settings.argon2_parallelism,
            ),
        )
    )


def get_password_hash(settings: Settings | None = None) -> PasswordHash:
    """Devolve o hasher, reconstruindo apenas quando o custo muda."""
    global _hasher, _hasher_cost

    settings = settings or get_settings()
    cost = (settings.argon2_time_cost, settings.argon2_memory_cost, settings.argon2_parallelism)
    if _hasher is None or _hasher_cost != cost:
        _hasher = _build_hasher(settings)
        _hasher_cost = cost
    return _hasher


def reset_password_hasher() -> None:
    """Descarta o hasher memoizado. Usado em teste ao trocar a configuração."""
    global _hasher, _hasher_cost
    _hasher = None
    _hasher_cost = None


class SecurityError(RuntimeError):
    """Falha de segurança: token inválido, expirado ou segredo ausente."""


class TokenExpired(SecurityError):
    """Token expirado. Distinto de inválido para permitir refresh automático."""


class TokenInvalid(SecurityError):
    """Token malformado ou com assinatura inválida."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


# --- Senha --------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Gera o hash Argon2 da senha. Nunca armazenamos a senha em claro."""
    if not password:
        raise SecurityError("senha não pode ser vazia")
    return get_password_hash().hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Confere a senha contra o hash.

    Devolve `False` em vez de levantar quando o hash é inválido: um hash corrompido
    não deve virar erro 500 e revelar que aquele usuário existe.
    """
    if not password or not password_hash:
        return False
    try:
        return get_password_hash().verify(password, password_hash)
    except Exception:  # noqa: BLE001 - hash malformado é falha de verificação
        return False


def needs_rehash(password_hash: str) -> bool:
    """True quando o hash foi gerado com parâmetros de custo desatualizados.

    Compara com o custo configurado agora, então aumentar o custo faz os hashes
    antigos serem regravados no próximo login bem-sucedido.
    """
    try:
        return get_password_hash().needs_update(password_hash)
    except Exception:  # noqa: BLE001
        return True


def validate_password_strength(password: str) -> list[str]:
    """Regras mínimas de senha. Devolve a lista de problemas, não levanta.

    Sem regra nenhuma, "123456" seria aceita — e a API fica exposta na internet.
    """
    problems: list[str] = []
    if len(password) < 10:
        problems.append("a senha deve ter ao menos 10 caracteres")
    if password.isdigit() or password.isalpha():
        problems.append("a senha deve misturar letras e números")
    if password.lower() in {
        "password",
        "senha",
        "123456",
        "1234567890",
        "admin",
        "administrador",
        "marketton",
    }:
        problems.append("a senha é uma das mais usadas e não oferece proteção")
    return problems


# --- Tokens -------------------------------------------------------------------


def create_access_token(
    *,
    subject: str,
    role: str,
    extra: dict[str, Any] | None = None,
    settings: Settings | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Emite um access token assinado, com papel embutido."""
    settings = settings or get_settings()
    now = datetime.now(UTC)
    expires = now + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        # `jti` permite revogar um token específico se necessário.
        "jti": secrets.token_urlsafe(16),
        "typ": "access",
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Valida assinatura e expiração. Distingue expirado de inválido."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid(f"token inválido: {exc}") from exc

    if payload.get("typ") != "access":
        raise TokenInvalid("token não é de acesso")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Gera um refresh token e o hash que será persistido.

    Devolve `(token_em_claro, hash)`. O token em claro só existe nesta resposta;
    o banco guarda apenas o hash.
    """
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    """SHA-256 do token.

    Aqui SHA-256 basta — diferente de senha. O token tem 48 bytes de entropia
    aleatória, então não há espaço de busca para ataque de dicionário; o que
    importa é ser determinístico para permitir a consulta.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token_pair(
    *,
    subject: str,
    role: str,
    settings: Settings | None = None,
) -> tuple[TokenPair, str, datetime]:
    """Emite o par de tokens.

    Devolve também o token de refresh em claro e sua expiração, para que o chamador
    persista o hash sem precisar recalculá-lo.
    """
    settings = settings or get_settings()
    access = create_access_token(subject=subject, role=role, settings=settings)
    refresh_plain, refresh_hash = generate_refresh_token()
    refresh_expires = datetime.now(UTC) + timedelta(days=30)

    pair = TokenPair(
        access_token=access,
        refresh_token=refresh_plain,
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return pair, refresh_hash, refresh_expires


def generate_jwt_secret() -> str:
    """Segredo forte para colocar no `.env`."""
    return secrets.token_urlsafe(64)


__all__ = [
    "ALGORITHM",
    "SecurityError",
    "TokenExpired",
    "TokenInvalid",
    "TokenPair",
    "create_access_token",
    "create_token_pair",
    "decode_access_token",
    "generate_jwt_secret",
    "generate_refresh_token",
    "get_password_hash",
    "hash_password",
    "hash_refresh_token",
    "needs_rehash",
    "reset_password_hasher",
    "validate_password_strength",
    "verify_password",
]
