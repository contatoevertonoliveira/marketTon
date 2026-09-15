#!/usr/bin/env python3
"""Gera o segredo JWT para colocar no `.env`.

Por que isto existe: `JWT_SECRET_KEY` tem um valor de desenvolvimento embutido
(`dev-only-insecure-change-me`). Um segredo conhecido permite **forjar um token de
administrador** — qualquer pessoa que leia o repositório entra como admin.

O sistema avisa em vez de falhar, porque precisa subir em desenvolvimento. Mas o
aviso só é acionável se houver um caminho óbvio para resolver, e é este.

Uso:
    python scripts/generate_jwt_secret.py
    python scripts/generate_jwt_secret.py --write     # grava no .env
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.services.security import generate_jwt_secret  # noqa: E402

ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
KEY = "JWT_SECRET_KEY"
DEV_VALUE = "dev-only-insecure-change-me"


def write_to_env(secret: str) -> tuple[bool, str]:
    """Escreve o segredo no `.env`, preservando o resto do arquivo.

    Devolve `(gravado, mensagem)`. Não cria o `.env` a partir do zero: se ele não
    existe, o usuário ainda não copiou o template e criar um arquivo só com o
    segredo esconderia essa etapa.
    """
    if not ENV_PATH.exists():
        return False, (
            f"{ENV_PATH.name} não existe. Rode `cp .env.example .env` primeiro, "
            "depois este script novamente."
        )

    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{KEY}=.*$", re.MULTILINE)

    if pattern.search(content):
        updated = pattern.sub(f"{KEY}={secret}", content)
    else:
        updated = content.rstrip("\n") + f"\n{KEY}={secret}\n"

    ENV_PATH.write_text(updated, encoding="utf-8")
    return True, f"{KEY} atualizado em {ENV_PATH.name}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera o segredo JWT do marketTon.")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"grava o valor em {ENV_PATH.name} em vez de apenas imprimir",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="sobrescreve um segredo já configurado (invalida tokens emitidos)",
    )
    args = parser.parse_args()

    secret = generate_jwt_secret()

    if args.write:
        if ENV_PATH.exists() and not args.force:
            current = ENV_PATH.read_text(encoding="utf-8")
            match = re.search(rf"^{KEY}=(.*)$", current, re.MULTILINE)
            if match and match.group(1).strip() not in ("", DEV_VALUE):
                print(
                    f"Já existe um {KEY} configurado. Use --force para substituí-lo "
                    "(isso invalida todos os tokens emitidos).",
                    file=sys.stderr,
                )
                return 1

        ok, message = write_to_env(secret)
        print(message)
        if not ok:
            return 1
        print("\nReinicie a API para o novo segredo valer.")
        print("Tokens emitidos com o segredo antigo deixarão de funcionar — esperado.")
        return 0

    print(secret)
    print(
        f"\nCopie para o .env (ou rode com --write para gravar):\n  {KEY}={secret}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
