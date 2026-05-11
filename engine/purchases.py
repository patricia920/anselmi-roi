#!/usr/bin/env python3
"""
purchases.py — Relatório de Compras (sugestão de pedido ao fornecedor).

Output: data/volution/purchases-report.json.gz

Fórmulas inferidas em 06_algoritmos_inferidos.md §13.

Defaults Anselmi:
  lead_time_weeks = 3   (LT ressuprimento fornecedor)
  period_weeks    = 4   (período de cobertura)
  cob_dep_weeks   = 1   (cobertura mínima depósito)

Lógica do pedido:
  demanda_horizon = velocidade_total_semanal × (lead + period)
  estoque_total   = estoque_lojas + estoque_depósito + recepções_pendentes
  pedido_bruto    = max(0, demanda_horizon + cob_dep_weeks × velocidade − estoque_total)
  pedido_ajustado = aplica capacidades + bloqueios + arredondamento múltiplo

Schema do row de saída (paridade com compras.html):
  {
    rootProductCode, rootProductName, classification1, classification2,
    salesVelocityWeekly,
    storeStock, depositStock, totalStock,
    pendingReception,
    leadTimeWeeks, periodWeeks, depCoverageWeeks,
    grossOrder, adjustedOrder, costOrderBRL,
    rupturaImminentDays,                  # dias até zerar
    rupturaDeposit,                       # dias até zerar depósito
    blocked,                              # se bloqueio produtivo
  }
"""

from __future__ import annotations

from typing import Any

from _common import (
    cli_main,
    get_code,
    get_desc,
    get_expr,
    load_engine_data,
    load_sisplan,
    replenishment_rows,
    save_report,
)


# Defaults Anselmi (de §13.2 — confirmadas em 7/7 amostras)
LEAD_WEEKS_DEFAULT = 3
PERIOD_WEEKS_DEFAULT = 4
COB_DEP_WEEKS_DEFAULT = 1


def _load_blocked_skus() -> set[str]:
    """Lê params Anselmi e retorna set de SKUs com bloqueio produtivo."""
    try:
        params = load_engine_data("params_anselmi.json")
    except FileNotFoundError:
        return set()
    blocked = set()
    for b in params.get("bloqueios", []):
        codes = b.get("produtos") or b.get("rootProductCodes") or []
        for c in codes:
            blocked.add(str(c).strip())
    return blocked


def _load_wh_stock() -> dict[str, float]:
    """data/sisplan/vw_wh_stock_roi.json → mapa rootProductCode → qtd estoque CD."""
    try:
        wh = load_sisplan("wh_stock_roi")
    except FileNotFoundError:
        return {}
    out: dict[str, float] = {}
    rows = wh if isinstance(wh, list) else (wh.get("rows") or [])
    for r in rows:
        code = (
            r.get("rootproductcode")
            or r.get("rootProductCode")
            or r.get("productcode")
            or r.get("CODIGO")
        )
        qtd = r.get("qtd") or r.get("quantity") or r.get("actualstock") or 0
        if not code:
            continue
        try:
            out[str(code).strip()] = out.get(str(code).strip(), 0.0) + float(qtd)
        except (TypeError, ValueError):
            pass
    return out


def _round_lot(qty: float, lot: int = 1) -> int:
    """Arredonda pra cima pro múltiplo do lote mínimo."""
    if lot <= 1:
        return int(round(qty))
    import math
    return int(math.ceil(qty / lot) * lot)


def run(*, dry_run: bool = False) -> dict:
    base_rows = replenishment_rows()
    blocked_skus = _load_blocked_skus()
    wh_stock = _load_wh_stock()

    out_rows: list[dict] = []
    for r in base_rows:
        code = get_code(r)
        if not code:
            continue
        actual_stock_lojas = get_expr(r, "actualStock")
        sales_proj = get_expr(r, "salesProjection")  # mensal
        velocity_weekly = sales_proj / 4.33 if sales_proj else 0.0
        recep = get_expr(r, "purchaseOrder")  # recepções pendentes (motor Volution)

        deposit_stock = wh_stock.get(code, 0.0)
        total_stock = actual_stock_lojas + deposit_stock + recep

        lead = LEAD_WEEKS_DEFAULT
        period = PERIOD_WEEKS_DEFAULT
        cob_dep = COB_DEP_WEEKS_DEFAULT

        demand_horizon = velocity_weekly * (lead + period)
        cob_dep_qty = velocity_weekly * cob_dep
        gross_order = max(0.0, demand_horizon + cob_dep_qty - total_stock)

        is_blocked = code in blocked_skus
        adjusted_order = 0 if is_blocked else _round_lot(gross_order, lot=1)

        # Custos / dias até zerar
        days_to_zero = (actual_stock_lojas / velocity_weekly * 7) if velocity_weekly > 0 else 999
        days_to_zero_dep = (deposit_stock / velocity_weekly * 7) if velocity_weekly > 0 else 999

        # Custo do pedido — sem unit cost confiável aqui, deixa em 0 e completa
        # no overstock (que tem unit_cost map). Pra usar na tela compras.html, o
        # frontend pode calcular via custo_unitário se dispensável.
        out_rows.append({
            "rootProductCode": code,
            "rootProductName": get_desc(r),
            "salesVelocityWeekly": round(velocity_weekly, 3),
            "storeStock": actual_stock_lojas,
            "depositStock": deposit_stock,
            "totalStock": round(total_stock, 1),
            "pendingReception": recep,
            "leadTimeWeeks": lead,
            "periodWeeks": period,
            "depCoverageWeeks": cob_dep,
            "demandHorizon": round(demand_horizon, 1),
            "grossOrder": round(gross_order, 1),
            "adjustedOrder": adjusted_order,
            "rupturaImminentDays": round(days_to_zero, 0),
            "rupturaDepositDays": round(days_to_zero_dep, 0),
            "blocked": is_blocked,
        })

    # Sort por adjustedOrder desc
    out_rows.sort(key=lambda x: x.get("adjustedOrder", 0), reverse=True)

    return save_report(
        "purchases",
        out_rows,
        endpoint="engine/purchases.py",
        extra={
            "defaults": {
                "lead_time_weeks": LEAD_WEEKS_DEFAULT,
                "period_weeks": PERIOD_WEEKS_DEFAULT,
                "dep_coverage_weeks": COB_DEP_WEEKS_DEFAULT,
            },
            "method": "max(0, velocity*(lead+period) + cob_dep − (lojas + deposito + recep))",
            "source": "replenishment-report + sisplan/vw_wh_stock_roi + params_anselmi.bloqueios",
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("purchases", run))
