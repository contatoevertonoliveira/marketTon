import os
import re
from pathlib import Path
from typing import Any

ROOT = Path("/home/evertonoliveira/marketTon")


def resolve_env_path() -> Path:
    return ROOT / ".env"


def _normalize_key(*parts: str) -> str:
    return "_".join(str(p).strip().upper() for p in parts if str(p).strip())


def _flatten_config(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for marketplace, cfg in (payload or {}).items():
        prefix = str(marketplace).upper()
        enabled = "true" if bool(cfg.get("enabled", True)) else "false"
        out[_normalize_key(prefix, "ENABLED")] = enabled
        out[_normalize_key(prefix, "MODE")] = str(cfg.get("mode", "affiliate"))
        scope = cfg.get("scope") or "national,international"
        out[_normalize_key(prefix, "SCOPE")] = scope
        for key, value in (cfg.get("values") or {}).items():
            if not isinstance(value, str):
                continue
            name = _normalize_key(prefix, key)
            out[name] = value
    return out


def read_existing_env(path: Path) -> dict[str, str]:
    existing: dict[str, str] = {}
    if not path.exists():
        return existing
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            continue
        existing[m.group(1).strip()] = m.group(2).strip()
    return existing


def apply_config(payload: dict[str, Any]) -> dict[str, Any]:
    env_path = resolve_env_path()
    merged = read_existing_env(env_path)
    merged.update(_flatten_config(payload))
    lines = []
    for key, value in merged.items():
        if value == "":
            lines.append(f"{key}=")
            continue
        if any(c in value for c in [" ", "#", '"', "'"]):
            value = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(env_path)}


def get_config() -> dict[str, Any]:
    env_path = resolve_env_path()
    existing = read_existing_env(env_path)
    marketplaces: dict[str, dict[str, Any]] = {}
    for path in sorted(ROOT.glob("integrations/marketplaces/config.*.env")):
        stem = path.stem
        if stem == "config.example":
            continue
        mp = stem.rsplit(".", 1)[0]
        data: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                data[m.group(1).strip()] = m.group(2).strip()
        enabled = data.pop("ENABLED", "true")
        mode = data.pop("MODE", "affiliate")
        scope = data.pop("SCOPE", "national,international")
        # include env overrides but don’t leak secrets unnecessarily
        merged = {**data, **{k: v for k, v in existing.items() if k.lower().startswith(mp)}}
        marketplaces[mp] = {
            "enabled": enabled.lower() != "false",
            "mode": mode if mode in {"affiliate", "dropshipping", "both"} else "affiliate",
            "scope": scope,
            "values": merged,
            "source": str(path),
        }
    if not marketplaces:
        return {}
    return {"marketplaces": marketplaces}


def get_marketplace(marketplace: str) -> dict[str, Any] | None:
    cfg = get_config()
    return cfg.get("marketplaces", {}).get(marketplace)


def login_mercadolivre(state: str | None = None) -> dict[str, Any]:
    client_id = os.getenv("MARKETPLACE_MERCADOLIVRE_CLIENT_ID", "")
    redirect_uri = os.getenv("MARKETPLACE_MERCADOLIVRE_REDIRECT_URI", "")
    if not client_id or not redirect_uri:
        return {"ok": False, "error": "missing_client_id_or_redirect_uri"}
    state = (state or "state").strip()
    if not state:
        state = "state"
    url = (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={client_id}"
        f"&redirect_uri={redirect_uri}&state={state}"
    )
    return {"ok": True, "url": url}
