#!/usr/bin/env python3
"""
_common.py — helpers compartilhados pelos motores ROI.

Cada motor lê dos JSONs Sisplan / Oracle / Volution sincronizados pelos
workflows existentes (sync_sisplan, query_oracle, sync_volution) e escreve
seu próprio {nome}-report.json.gz em data/volution/.

Estrutura esperada do repo (rodando como cwd = raiz do anselmi-pcp):
  data/sisplan/*.json          ← input (vw_actual_stock_roi, vw_vendas_roi, etc.)
  data/oracle/*.json[.gz]      ← input (vw_giro_estoque, vw_giro_venda, etc.)
  data/volution/*.json.gz      ← input/output (replenishment-report, minimum-stock, ...)
  roi/engine/data/             ← parâmetros estáticos (curva sazonal, params Anselmi)
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Brasil-3 timezone (offset fixo, sem DST porque ROI Volution roda em -03 fixo)
BRT = timezone(timedelta(hours=-3), name="BRT")


# ============================================================================
# RESOLUÇÃO DE PATHS
# ============================================================================
# O motor pode ser invocado de qualquer cwd. Resolvemos sempre a partir de
# $ANSELMI_PCP_ROOT (env var) ou subindo até achar `data/` + `roi/`.

def repo_root() -> Path:
    env = os.environ.get("ANSELMI_PCP_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "data" / "sisplan").is_dir() and (p / "roi" / "engine").is_dir():
            return p
    # Fallback: se a estrutura ainda não tá no repo, usa o pai do engine/
    return here.parents[1]


ROOT = repo_root()
SISPLAN_DIR = ROOT / "data" / "sisplan"
ORACLE_DIR = ROOT / "data" / "oracle"
VOLUTION_DIR = ROOT / "data" / "volution"
ENGINE_DATA_DIR = Path(__file__).resolve().parent / "data"


# ============================================================================
# LOADERS
# ============================================================================

def _read_text(path: Path) -> str:
    if path.suffix == ".gz" or path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fp:
            return fp.read()
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def load_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def load_sisplan(view: str) -> list[dict] | dict:
    """Carrega data/sisplan/{view}.json. Aceita 'vw_actual_stock_roi' ou nome curto."""
    candidates = [
        SISPLAN_DIR / f"{view}.json",
        SISPLAN_DIR / f"vw_{view}.json",
        SISPLAN_DIR / f"vw_{view}_roi.json",
    ]
    for p in candidates:
        if p.is_file():
            return load_json(p)
    raise FileNotFoundError(f"sisplan view não encontrada: {view} (tentei {candidates})")


def load_oracle(view: str) -> list[dict] | dict:
    """Carrega data/oracle/{view}.json[.gz]. Lida com .json e .json.gz."""
    candidates = [
        ORACLE_DIR / f"{view}.json",
        ORACLE_DIR / f"{view}.json.gz",
        ORACLE_DIR / f"vw_{view}.json",
        ORACLE_DIR / f"vw_{view}.json.gz",
    ]
    for p in candidates:
        if p.is_file():
            return load_json(p)
    raise FileNotFoundError(f"oracle view não encontrada: {view} (tentei {candidates})")


def load_volution(name: str) -> dict:
    """Carrega data/volution/{name}.json.gz (formato {exported_at, rows, ...})."""
    p = VOLUTION_DIR / f"{name}.json.gz"
    if not p.is_file():
        # tenta sem -report
        p2 = VOLUTION_DIR / f"{name}-report.json.gz"
        if p2.is_file():
            p = p2
    if not p.is_file():
        raise FileNotFoundError(f"volution arquivo não encontrado: {name}")
    return load_json(p)


def load_engine_data(filename: str) -> Any:
    """Carrega arquivo estático em roi/engine/data/ (curva sazonal, params)."""
    p = ENGINE_DATA_DIR / filename
    if not p.is_file():
        # fallback: ROI top-level (compat com cópia atual em /Users/pipi/.../ROI/)
        p2 = ROOT / filename
        if p2.is_file():
            p = p2
    if not p.is_file():
        raise FileNotFoundError(f"engine data não encontrado: {filename}")
    return load_json(p)


# ============================================================================
# WRITER
# ============================================================================

def save_report(
    name: str,
    rows: list[dict],
    *,
    endpoint: str = "",
    extra: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """Escreve data/volution/{name}-report.json.gz com schema padrão do MVP.

    Schema:
      {
        "exported_at": "<ISO -03:00>",
        "endpoint": "<motor que gerou>",
        "rows_count": N,
        "rows": [...],
        ...extra
      }
    Retorna metadata: {file, bytes, rows_count, dry_run}.
    """
    payload = {
        "exported_at": datetime.now(BRT).isoformat(timespec="seconds"),
        "endpoint": endpoint or f"engine/{name}.py",
        "rows_count": len(rows),
        "rows": rows,
    }
    if extra:
        payload.update(extra)

    if dry_run:
        return {"file": None, "bytes": 0, "rows_count": len(rows), "dry_run": True}

    VOLUTION_DIR.mkdir(parents=True, exist_ok=True)
    out_path = VOLUTION_DIR / f"{name}-report.json.gz"
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(out_path, "wb", compresslevel=6) as fp:
        fp.write(raw)
    bytes_written = out_path.stat().st_size
    return {
        "file": str(out_path),
        "bytes": bytes_written,
        "rows_count": len(rows),
        "dry_run": False,
    }


# ============================================================================
# SCHEMA HELPERS — Volution replenishment-report.json.gz (já existe no PCP)
# ============================================================================

def replenishment_rows() -> list[dict]:
    """Lê data/volution/replenishment-report.json.gz e retorna rows.

    Cada row tem expressions = {orders, originalOrder, transferIn, transferOut,
    returns, overstock, actualStock, salesProjection, minimumStock, totalSales,
    selltrough, purchaseOrder} + pointsOfSaleRanking[].

    Esse é o ground truth do motor Volution — usar como fonte primária quando
    disponível, em vez de recalcular do zero a partir de Sisplan.
    """
    data = load_volution("replenishment-report")
    return data.get("rows", []) or []


def get_expr(row: dict, key: str) -> float:
    """Extrai expressions[key] do schema Volution. Lida com objeto {value} ou primitivo."""
    e = row.get("expressions") or {}
    v = e.get(key)
    if v is None:
        return 0.0
    if isinstance(v, dict) and "value" in v:
        return float(v["value"] or 0)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def get_code(row: dict) -> str:
    return (
        row.get("rootProductCode")
        or row.get("productCode")
        or row.get("code")
        or (row.get("product") or {}).get("code")
        or (row.get("product") or {}).get("rootProductCode")
        or ""
    )


def get_desc(row: dict) -> str:
    return (
        row.get("rootProductName")
        or row.get("productName")
        or row.get("description")
        or (row.get("product") or {}).get("name")
        or (row.get("product") or {}).get("description")
        or ""
    )


# ============================================================================
# CLI ENVELOPE
# ============================================================================

def cli_main(name: str, run_fn):
    """Envelope CLI padrão. Uso nos motores:

        if __name__ == '__main__':
            from _common import cli_main
            cli_main('overstock', run)

    Onde `run(dry_run: bool) -> dict` faz o trabalho e retorna metadata.
    """
    dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "1"
    print(f"[{name}] start  cwd={os.getcwd()}  root={ROOT}  dry_run={dry}", flush=True)
    try:
        meta = run_fn(dry_run=dry)
        print(f"[{name}] done   {meta}", flush=True)
        return 0
    except Exception as e:
        import traceback
        print(f"[{name}] ERROR  {e}", file=sys.stderr)
        traceback.print_exc()
        return 1
