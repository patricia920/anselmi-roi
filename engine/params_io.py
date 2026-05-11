#!/usr/bin/env python3
"""
params_io.py — Leitor/escritor de data/volution/params-state.json.

NÃO usa .json.gz porque o frontend (parametros.html) lê esse arquivo direto e
o Worker /api/edit-file precisa fazer PUT em texto JSON.

Funções:
  load_state()    → dict com bloqueios, cobertura, estoque_minimo, sazonalidades, capacidades
  save_state(s)   → grava data/volution/params-state.json
  bootstrap()     → cria o arquivo a partir de roi/engine/data/params_anselmi.json se faltar

Uso CLI:
  python params_io.py [--bootstrap] [--show]
  python params_io.py --bootstrap        # cria params-state.json a partir do snapshot estático
  python params_io.py --show             # imprime estado atual (resumido)

O Worker /api/edit-file (Cloudflare Pages Function) é o que escreve do
frontend pro repo. Esse script Python é pra:
  1. Bootstrap inicial no primeiro deploy
  2. Migrações futuras de schema
  3. Validação opcional antes do compute_roi rodar
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _common import BRT, ENGINE_DATA_DIR, VOLUTION_DIR, load_engine_data


STATE_FILE = VOLUTION_DIR / "params-state.json"


# ============================================================================
# SCHEMA DEFAULT
# ============================================================================

DEFAULT_STATE: dict[str, Any] = {
    "version": "v1",
    "exported_at": None,
    "params": {
        "bloqueios": [],
        "cobertura": {
            "padrao_lojas_semanas": 4,
            "padrao_deposito_semanas": 1,
            "regras_personalizadas": [],
        },
        "estoque_minimo": [],   # 25 itens (categoria × tamanho × loja)
        "sazonalidades": [],    # 6 itens (categoria × meses)
        "capacidades": [],      # capacidade max por loja/categoria
    },
}


# ============================================================================
# LOAD / SAVE
# ============================================================================

def load_state() -> dict:
    """Carrega params-state.json. Se não existir, retorna DEFAULT_STATE."""
    if not STATE_FILE.is_file():
        return DEFAULT_STATE
    with open(STATE_FILE, "r", encoding="utf-8") as fp:
        return json.load(fp)


def save_state(state: dict) -> dict:
    """Grava params-state.json com timestamp atualizado."""
    state["exported_at"] = datetime.now(BRT).isoformat(timespec="seconds")
    state["version"] = state.get("version", "v1")
    VOLUTION_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fp:
        json.dump(state, fp, ensure_ascii=False, indent=2)
    return {
        "file": str(STATE_FILE),
        "bytes": STATE_FILE.stat().st_size,
        "version": state["version"],
        "exported_at": state["exported_at"],
    }


def bootstrap(force: bool = False) -> dict:
    """Inicializa params-state.json com os valores capturados do ROI Volution
    (snapshot 06/05/2026 em roi/engine/data/params_anselmi.json).

    Se o arquivo já existe e force=False, retorna no-op.
    """
    if STATE_FILE.is_file() and not force:
        return {"action": "skipped", "reason": "params-state.json já existe", "file": str(STATE_FILE)}

    try:
        snapshot = load_engine_data("params_anselmi.json")
    except FileNotFoundError:
        # Sem snapshot: cria estado vazio
        return save_state({**DEFAULT_STATE})

    # Mapeia o snapshot pro schema do state
    state = {
        "version": "v1",
        "params": {
            "bloqueios": snapshot.get("bloqueios", []),
            "cobertura": snapshot.get("cobertura", DEFAULT_STATE["params"]["cobertura"]),
            "estoque_minimo": snapshot.get("estoque_minimo", []),
            "sazonalidades": snapshot.get("sazonalidades", []),
            "capacidades": snapshot.get("capacidades", []),
        },
        "_source": "roi/engine/data/params_anselmi.json (snapshot 06/05/2026 19h)",
    }
    return save_state(state)


# ============================================================================
# VALIDAÇÃO
# ============================================================================

def validate_state(state: dict) -> list[str]:
    """Valida campos esperados. Retorna lista de problemas (vazia = ok)."""
    problems = []
    if "params" not in state:
        problems.append("missing field: params")
        return problems
    p = state["params"]
    for key in ("bloqueios", "cobertura", "estoque_minimo", "sazonalidades", "capacidades"):
        if key not in p:
            problems.append(f"missing field: params.{key}")
    cob = p.get("cobertura", {})
    if not isinstance(cob, dict):
        problems.append("params.cobertura must be object")
    return problems


# ============================================================================
# CLI
# ============================================================================

def _cmd_show():
    state = load_state()
    p = state.get("params", {})
    print(f"params-state.json @ {STATE_FILE}")
    print(f"  version       : {state.get('version')}")
    print(f"  exported_at   : {state.get('exported_at')}")
    print(f"  bloqueios     : {len(p.get('bloqueios', []))}")
    print(f"  estoque_minimo: {len(p.get('estoque_minimo', []))} regras")
    print(f"  sazonalidades : {len(p.get('sazonalidades', []))} curvas")
    print(f"  capacidades   : {len(p.get('capacidades', []))} regras")
    cob = p.get("cobertura", {})
    print(f"  cobertura     : padrao_lojas={cob.get('padrao_lojas_semanas')} sem")
    problems = validate_state(state)
    if problems:
        print("  ⚠ problemas:")
        for pb in problems:
            print(f"    - {pb}")
    else:
        print("  ✓ schema válido")


def main() -> int:
    if "--bootstrap" in sys.argv:
        force = "--force" in sys.argv
        result = bootstrap(force=force)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if "--show" in sys.argv or len(sys.argv) == 1:
        _cmd_show()
        return 0
    print("uso: python params_io.py [--bootstrap [--force]] [--show]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
