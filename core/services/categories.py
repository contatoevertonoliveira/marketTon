"""Nome legível de categoria por marketplace, para agrupar produtos em seções.

O catálogo guarda só o ID. Mercado Livre: API pública de categorias (cache em
memória por processo). Shopee: a API de afiliados não expõe nomes; os
departamentos abaixo vêm dos feeds de itens (`global_catid1`/`global_category1`,
mesmo espaço de IDs de `productCatIds`, conferido em 6 itens) e foram
traduzidos. ID desconhecido cai em "Categoria <id>" — nunca um nome inventado.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

SHOPEE_DEPARTMENTS_PT = {
    "100001": "Saúde",
    "100009": "Acessórios de Moda",
    "100010": "Eletrodomésticos",
    "100011": "Roupas Masculinas",
    "100012": "Calçados Masculinos",
    "100013": "Celulares e Acessórios",
    "100015": "Viagem e Bagagem",
    "100016": "Bolsas Femininas",
    "100017": "Roupas Femininas",
    "100532": "Calçados Femininos",
    "100533": "Bolsas Masculinas",
    "100534": "Relógios",
    "100535": "Áudio",
    "100629": "Alimentos e Bebidas",
    "100630": "Beleza",
    "100631": "Pets",
    "100632": "Mãe e Bebê",
    "100633": "Moda Infantil",
    "100634": "Games e Consoles",
    "100635": "Câmeras e Drones",
    "100636": "Casa e Decoração",
    "100637": "Esportes e Lazer",
    "100638": "Papelaria",
    "100639": "Hobbies e Colecionáveis",
    "100643": "Livros e Revistas",
    "100644": "Computadores e Acessórios",
    "102187": "Peças e Acessórios para Veículos",
}

_ml_cache: dict[str, str] = {}


def _ml_department(category_id: str) -> str:
    if category_id in _ml_cache:
        return _ml_cache[category_id]
    name = f"Categoria {category_id}"
    try:
        response = requests.get(f"https://api.mercadolibre.com/categories/{category_id}", timeout=6)
        response.raise_for_status()
        data = response.json()
        root = (data.get("path_from_root") or [None])[0]
        name = (root or data).get("name") or name
        _ml_cache[category_id] = name
    except (requests.RequestException, ValueError):
        logger.warning("não foi possível resolver a categoria ML %s", category_id)
    return name


def department_name(marketplace: str, category_id: str | None) -> str:
    """Departamento (nível 1) do produto, ou "Sem categoria" quando não há ID."""
    if not category_id:
        return "Sem categoria"
    if marketplace == "shopee":
        return SHOPEE_DEPARTMENTS_PT.get(str(category_id), f"Categoria {category_id}")
    if marketplace == "mercado_livre":
        return _ml_department(str(category_id))
    return f"Categoria {category_id}"
