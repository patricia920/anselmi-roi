#!/usr/bin/env python3
"""
transfers.py — Relatório de Transferências loja → loja.

Output: data/volution/transfers-report.json.gz

Fórmula validada em 06_algoritmos_inferidos.md §12:

  Para cada SKU:
    déficit_loja_X = max(0, estoque_minimo_X - estoque_atual_X)
    sobra_loja_Y   = max(0, estoque_atual_Y - estoque_ideal_Y)
    qtd_transfer(Y → X) = min(sobra_loja_Y, déficit_loja_X)

  Margem da transferência (potencial de venda recuperada):
    margem_R$ = qtd × (preço_venda_X - custo_unit) × probabilidade_venda

Schema do row de saída (paridade com transferencias.html):
  {
    rootProductCode, rootProductName, classification1, classification2,
    sourceStoreCode, sourceStoreName,    # origem (sobra)
    targetStoreCode, targetStoreName,    # destino (déficit)
    quantity,                            # qtd a transferir
    sourceStockBefore, sourceStockAfter,
    targetStockBefore, targetStockAfter,
    salesVelocityTarget,                 # vendas/sem na loja destino
    estimatedRecoveryR$,                 # margem recuperada
    transferType,                        # "rebalance" | "consolidation"
  }
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from _common import (
    cli_main,
    get_code,
    get_desc,
    get_expr,
    replenishment_rows,
    save_report,
)


def _index_by_sku_pos(rows: list[dict]) -> dict[str, list[dict]]:
    """Indexa replenishment rows por SKU. pointsOfSaleRanking real tem
    currentStock + salesTwoMonths por loja (top 10 por SKU).

    Não vem minimumStock por loja — rateamos via:
        minimum_loja = minimumStock_total × (salesTwoMonths_loja / Σ salesTwoMonths)
        ideal_loja   = minimum_loja × 1.3
    """
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        code = get_code(r)
        if not code:
            continue
        pos_ranking = r.get("pointsOfSaleRanking") or []
        if not pos_ranking:
            continue
        total_sales = sum(float(p.get("salesTwoMonths") or 0) for p in pos_ranking) or 1
        min_total = get_expr(r, "minimumStock")
        unit_price = float(r.get("price") or 0)
        unit_cost = float(r.get("cost") or 0)
        for pos in pos_ranking:
            sales_loja = float(pos.get("salesTwoMonths") or 0)
            peso = sales_loja / total_sales
            min_loja = min_total * peso
            out[code].append({
                "store_code": pos.get("name") or "",
                "store_name": pos.get("name") or "",
                "actual_stock": float(pos.get("currentStock") or 0),
                "minimum_stock": min_loja,
                "ideal_stock": min_loja * 1.3,
                "sales_velocity_weekly": sales_loja / 8.66,
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "_root_name": get_desc(r),
            })
    return out


def _compute_pairs(pos_rows: list[dict]) -> list[dict]:
    """Para um único SKU, casa lojas com sobra e lojas com déficit.

    Algoritmo guloso: ordena destinos por velocidade desc (prioriza onde mais
    vende), e origens por sobra desc. Pareia até zerar.
    """
    surpluses = [
        {**p, "surplus": p["actual_stock"] - p["ideal_stock"]}
        for p in pos_rows
        if (p["actual_stock"] - p["ideal_stock"]) > 0
    ]
    deficits = [
        {**p, "deficit": p["minimum_stock"] - p["actual_stock"]}
        for p in pos_rows
        if (p["minimum_stock"] - p["actual_stock"]) > 0
    ]
    if not surpluses or not deficits:
        return []

    surpluses.sort(key=lambda x: x["surplus"], reverse=True)
    deficits.sort(key=lambda x: x["sales_velocity_weekly"], reverse=True)

    pairs: list[dict] = []
    s_idx = 0
    for d in deficits:
        need = d["deficit"]
        while need > 0 and s_idx < len(surpluses):
            s = surpluses[s_idx]
            if s["surplus"] <= 0:
                s_idx += 1
                continue
            qty = min(s["surplus"], need)
            qty_int = int(qty)  # transferências são inteiros (peças)
            if qty_int <= 0:
                s_idx += 1
                continue
            margin = max(0.0, d["unit_price"] - s["unit_cost"])
            recovery = qty_int * margin
            pairs.append({
                "sourceStoreCode": s["store_code"],
                "sourceStoreName": s["store_name"],
                "targetStoreCode": d["store_code"],
                "targetStoreName": d["store_name"],
                "quantity": qty_int,
                "sourceStockBefore": s["actual_stock"],
                "sourceStockAfter": s["actual_stock"] - qty_int,
                "targetStockBefore": d["actual_stock"],
                "targetStockAfter": d["actual_stock"] + qty_int,
                "salesVelocityTarget": round(d["sales_velocity_weekly"], 2),
                "unitPrice": d["unit_price"],
                "unitCost": s["unit_cost"],
                "estimatedRecoveryBRL": round(recovery, 2),
                "transferType": "rebalance" if s["surplus"] - qty_int > 0 else "consolidation",
            })
            s["surplus"] -= qty_int
            need -= qty_int
    return pairs


def run(*, dry_run: bool = False) -> dict:
    rows = replenishment_rows()
    if not rows:
        return save_report("transfers", [], endpoint="engine/transfers.py", dry_run=dry_run)

    by_sku = _index_by_sku_pos(rows)
    out_rows: list[dict] = []
    for code, pos_rows in by_sku.items():
        if len(pos_rows) < 2:
            continue
        name = pos_rows[0].get("_root_name", "")
        for pair in _compute_pairs(pos_rows):
            out_rows.append({
                "rootProductCode": code,
                "rootProductName": name,
                **pair,
            })

    # Sort por estimatedRecoveryBRL desc (maior potencial primeiro)
    out_rows.sort(key=lambda x: x.get("estimatedRecoveryBRL", 0), reverse=True)

    return save_report(
        "transfers",
        out_rows,
        endpoint="engine/transfers.py",
        extra={
            "method": "qtd = min(surplus_origem, deficit_destino), greedy by velocity",
            "source": "data/volution/replenishment-report.json.gz (pointsOfSaleRanking)",
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("transfers", run))
