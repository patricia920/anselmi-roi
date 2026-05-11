#!/usr/bin/env python3
"""
stock_quality.py — Matriz Idade × Cobertura (Qualidade do Estoque).

Output: data/volution/stock-quality-report.json.gz

Matriz 5x5 que classifica cada SKU em um de 4 níveis:
  G  (Green)  — saudável: idade baixa + cobertura saudável
  Y1 (Yellow1) — atenção: cobertura alta OU idade alta isolada
  Y2 (Yellow2) — alerta: ambas medianas + alta
  R  (Red/tóxico) — crítico: idade alta + cobertura altíssima

Definições (06_algoritmos_inferidos.md §9):

  Idade (semanas)  = (hoje - data_primeiro_recebimento) em semanas
  Cobertura (sem)  = estoque_atual / velocidade_semanal

  Buckets idade: 0-4, 4-12, 12-26, 26-52, >52
  Buckets cob:   0-4, 4-12, 12-26, 26-52, >52

  Classificação (5x5 → cor):
    cob \\ idade  | 0-4 | 4-12 | 12-26 | 26-52 | >52
    --------------|-----|------|-------|-------|-----
    0-4           |  G  |  G   |  G    |  Y1   |  Y2
    4-12          |  G  |  G   |  Y1   |  Y2   |  R
    12-26         |  G  |  Y1  |  Y2   |  R    |  R
    26-52         |  Y1 |  Y2  |  R    |  R    |  R
    >52           |  Y2 |  R   |  R    |  R    |  R

Schema de saída (paridade com stock-quality.html):
  {
    matrix: 5x5 (idade × cobertura) com {qty, value, count} em cada célula,
    totals: {tóxico_pct, tóxico_BRL, médias},
    skus: [{rootProductCode, idade_sem, cobertura_sem, classification, qty, value}, ...]
  }
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from _common import (
    BRT,
    cli_main,
    get_code,
    get_desc,
    get_expr,
    load_oracle,
    load_sisplan,
    replenishment_rows,
    save_report,
)


AGE_BUCKETS = [(0, 4), (4, 12), (12, 26), (26, 52), (52, 999)]
COV_BUCKETS = [(0, 4), (4, 12), (12, 26), (26, 52), (52, 999)]
BUCKET_LABELS = ["0-4", "4-12", "12-26", "26-52", ">52"]

# Tabela de classificação 5x5 (rows=cobertura, cols=idade) — 06_algoritmos §9
CLASSIFICATION = [
    ["G",  "G",  "G",  "Y1", "Y2"],
    ["G",  "G",  "Y1", "Y2", "R"],
    ["G",  "Y1", "Y2", "R",  "R"],
    ["Y1", "Y2", "R",  "R",  "R"],
    ["Y2", "R",  "R",  "R",  "R"],
]


def _bucket_index(value: float, buckets: list[tuple[float, float]]) -> int:
    for i, (lo, hi) in enumerate(buckets):
        if lo <= value < hi:
            return i
    return len(buckets) - 1


def _classify(idade_sem: float, cobertura_sem: float) -> tuple[str, int, int]:
    """Retorna (classification, age_idx, cov_idx)."""
    age_idx = _bucket_index(idade_sem, AGE_BUCKETS)
    cov_idx = _bucket_index(cobertura_sem, COV_BUCKETS)
    return CLASSIFICATION[cov_idx][age_idx], age_idx, cov_idx


def _load_first_receipt_dates() -> dict[str, datetime]:
    """Lê data/sisplan/vw_stock_mov_roi.json e retorna primeiro recebimento por SKU.

    O arquivo é gigante (14MB). Aqui agregamos por (rootProductCode, MIN(data)).
    Se não existir, retorna {} e a idade vira 0 → cai todo no bucket 0-4.
    """
    try:
        mov = load_sisplan("stock_mov_roi")
    except FileNotFoundError:
        return {}

    rows = mov if isinstance(mov, list) else (mov.get("rows") or [])
    out: dict[str, datetime] = {}
    for r in rows:
        code = (
            r.get("rootproductcode")
            or r.get("rootProductCode")
            or r.get("productcode")
            or ""
        )
        if not code:
            continue
        # Filtra movimentos de RECEBIMENTO/ENTRADA (tipo varia por sistema)
        tipo = (r.get("tipo") or r.get("type") or r.get("operacao") or "").upper()
        if tipo and not any(k in tipo for k in ("RECEB", "ENTRADA", "RECEIVE", "RX")):
            continue
        data_str = (
            r.get("data")
            or r.get("date")
            or r.get("dt")
            or r.get("datamov")
            or r.get("dataemissao")
        )
        if not data_str:
            continue
        try:
            # Aceita 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS' e ISO com offset
            d = datetime.fromisoformat(str(data_str).replace("Z", "+00:00"))
        except ValueError:
            continue
        prev = out.get(str(code).strip())
        if prev is None or d < prev:
            out[str(code).strip()] = d
    return out


def run(*, dry_run: bool = False) -> dict:
    base_rows = replenishment_rows()
    first_recv = _load_first_receipt_dates()
    today = datetime.now(BRT)

    # Inicializa matriz 5x5 com {qty, value, count}
    matrix: list[list[dict]] = [
        [{"qty": 0.0, "value": 0.0, "count": 0, "class": CLASSIFICATION[c][a]} for a in range(5)]
        for c in range(5)
    ]

    skus_out: list[dict] = []
    cls_totals = {"G": 0.0, "Y1": 0.0, "Y2": 0.0, "R": 0.0}
    cls_counts = {"G": 0, "Y1": 0, "Y2": 0, "R": 0}
    total_value = 0.0

    for r in base_rows:
        code = get_code(r)
        if not code:
            continue
        actual_stock = get_expr(r, "actualStock")
        if actual_stock <= 0:
            continue
        sales_proj = get_expr(r, "salesProjection")
        velocity_weekly = sales_proj / 4.33 if sales_proj else 0.0

        cobertura = (actual_stock / velocity_weekly) if velocity_weekly > 0 else 99.0
        cobertura = min(cobertura, 99.0)

        first = first_recv.get(code)
        if first:
            # Normaliza tz
            if first.tzinfo is None:
                first = first.replace(tzinfo=BRT)
            idade_sem = (today - first).days / 7.0
        else:
            idade_sem = 0.0  # sem dado → assume novo

        cls, age_idx, cov_idx = _classify(idade_sem, cobertura)

        # Sem unit cost confiável aqui — usa estoque_atual como qty e
        # velocidade*4.33*4 (1 mês de venda) como valor aproximado.
        # Em produção ideal seria valor_estoque do vw_giro_estoque.
        cell = matrix[cov_idx][age_idx]
        cell["qty"] += actual_stock
        cell["value"] += actual_stock  # placeholder até unit_cost
        cell["count"] += 1
        cls_totals[cls] += actual_stock
        cls_counts[cls] += 1
        total_value += actual_stock

        skus_out.append({
            "rootProductCode": code,
            "rootProductName": get_desc(r),
            "actualStock": actual_stock,
            "salesVelocityWeekly": round(velocity_weekly, 3),
            "ageWeeks": round(idade_sem, 1),
            "coverageWeeks": round(cobertura, 1),
            "classification": cls,
            "ageBucket": BUCKET_LABELS[age_idx],
            "coverageBucket": BUCKET_LABELS[cov_idx],
        })

    # Sort SKUs: tóxico (R) primeiro, depois Y2, Y1, G
    cls_order = {"R": 0, "Y2": 1, "Y1": 2, "G": 3}
    skus_out.sort(key=lambda x: (cls_order.get(x["classification"], 9), -x["actualStock"]))

    totals = {
        "totalValue": round(total_value, 2),
        "totalCount": len(skus_out),
        "byClass": {
            cls: {
                "qty": round(cls_totals[cls], 2),
                "count": cls_counts[cls],
                "pct": round(cls_totals[cls] / total_value * 100, 1) if total_value else 0,
            }
            for cls in ("G", "Y1", "Y2", "R")
        },
    }

    return save_report(
        "stock-quality",
        skus_out,
        endpoint="engine/stock_quality.py",
        extra={
            "matrix": matrix,
            "matrix_axes": {
                "age_buckets": BUCKET_LABELS,
                "coverage_buckets": BUCKET_LABELS,
            },
            "totals": totals,
            "method": "Idade × Cobertura → tabela 5x5 G/Y1/Y2/R",
            "source": "replenishment-report + sisplan/vw_stock_mov_roi (primeiro receb)",
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("stock-quality", run))
