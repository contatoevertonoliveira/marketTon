"""Roda os testes em Node do validador da loja pública (função do Netlify), quando o Node está instalado."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node não instalado")
def test_store_validator_node_tests_pass():
    proc = subprocess.run(["node", "--test", "tests/js/loja_core.test.mjs", "tests/js/loja_render.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-1000:]
