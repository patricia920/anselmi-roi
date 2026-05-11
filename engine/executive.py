#!/usr/bin/env python3
"""
executive.py — Centro da empresa (KPIs executivos).

Output: data/volution/executive-report.json.gz

KPIs documentados em 06_algoritmos §16. Snapshot Anselmi YTD (06/05/2026):

  Vendas YTD          : R$ 43,0M  (+28% vs YoY)
  Margem Bruta YTD    : R$ 15,64M (+59% vs YoY)
  GMROII              : 105%
  Inventory Turn      : ~3.2x
  DV (Days of Stock)  : 47 dias
  Aceitação ROI       : 13% das transferências sugeridas
  Tickets             : N transações
  Ticket médio        : R$/transação
  Vendas Perdidas     : estimativa de R$ perdidos por ruptura

Schema do row de saída (paridade com centro-empresa.html):
  {
    kpis: {
      salesYTD: {value, yoy_pct},
      marginYTD: {value, yoy_pct},
      gmroii: {pct},
      turnover: {ratio},
      daysOfStock: {days, delta_yoy},
      transferAcceptance: {pct},
      tickets: {count},
      averageTicket: {value},
      lostSales: {value},
    },
    overstock: {pct, value, ...},
    monthlyTrend: [...]
  }
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from _common import (
    BRT,
    cli_main,
    get_expr,
    load_oracle,
    load_sisplan,
    replenishment_rows,
    save_report,
)


def _load_sales_ytd() -> tuple[float, float, int]:
    """Lê data/sisplan/vw_vendas_roi.json e calcula:
       (vendas_total_BRL, margem_total_BRL, transações_count) YTD.

    Sem schema confirmado. Tenta vários campos alternativos.
    """
    try:
        sales = load_sisplan("vendas_roi")
    except FileNotFoundError:
        return 0.0, 0.0, 0
    rows = sales if isinstance(sales, list) else (sales.get("rows") or [])
    total_value = 0.0
    total_margin = 0.0
    transactions = 0
    today = datetime.now(BRT)
    year_start = datetime(today.year, 1, 1, tzinfo=BRT)
    for r in rows:
        date_str = r.get("data") or r.get("date") or r.get("datavenda")
        if date_str:
            try:
                d = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=BRT)
                if d < year_start:
                    continue
            except ValueError:
                pass
        value = float(r.get("valor") or r.get("VALOR") or r.get("vlr_venda") or 0)
        margin = float(r.get("margem") or r.get("MARGEM") or r.get("vlr_margem") or 0)
        total_value += value
        total_margin += margin
        if value > 0:
            transactions += 1
    return total_value, total_margin, transactions


def _calc_overstock_metrics(rows: list[dict]) -> dict:
    """Sumariza overstock total a partir do replenishment-report."""
    total_overstock_units = 0.0
    total_overstock_value = 0.0  # placeholder até unit_cost confiável
    total_stock_units = 0.0
    for r in rows:
        actual = get_expr(r, "actualStock")
        over = get_expr(r, "overstock")
        total_stock_units += actual
        total_overstock_units += over
        total_overstock_value += over  # 1:1 sem unit_cost
    pct = (total_overstock_units / total_stock_units * 100) if total_stock_units else 0
    return {
        "totalStockUnits": int(total_stock_units),
        "overstockUnits": int(total_overstock_units),
        "overstockPct": round(pct, 1),
        "overstockValuePlaceholder": int(total_overstock_value),
    }


def _calc_transfer_acceptance() -> dict:
    """Lê data/oracle/vw_roi_storepending.json e calcula taxa de aceitação.

    Schema esperado: cada row representa uma sugestão; campo `accepted` ou
    `aceito` indica se foi efetivada. Snapshot 06/05: 13%.
    """
    try:
        rows = load_oracle("vw_roi_storepending")
    except FileNotFoundError:
        return {"pct": None, "note": "vw_roi_storepending não disponível"}
    rows = rows if isinstance(rows, list) else (rows.get("rows") or [])
    total = 0
    accepted = 0
    for r in rows:
        total += 1
        flag = (
            r.get("accepted")
            or r.get("aceito")
            or r.get("status")
            or r.get("ativo")
        )
        if isinstance(flag, str):
            if flag.upper() in ("S", "Y", "TRUE", "1", "ACEITO", "EFETIVADO", "CONFIRMADO"):
                accepted += 1
        elif flag in (True, 1):
            accepted += 1
    pct = (accepted / total * 100) if total else 0
    return {
        "totalSuggestions": total,
        "accepted": accepted,
        "pct": round(pct, 1),
    }


def _calc_lost_sales(rows: list[dict]) -> float:
    """Estimativa de vendas perdidas: SKUs com cobertura < 1 sem × velocity × preço.

    Sem unit_price confiável nas rows base, usa actualStock como proxy.
    """
    lost = 0.0
    for r in rows:
        actual = get_expr(r, "actualStock")
        velocity_weekly = get_expr(r, "salesProjection") / 4.33
        if velocity_weekly <= 0:
            continue
        coverage = actual / velocity_weekly
        if coverage < 1:
            # Quanto vendia se tivesse estoque pra +1 semana
            lost += velocity_weekly  # qty perdida
    return lost


def run(*, dry_run: bool = False) -> dict:
    rows = replenishment_rows()
    sales_value, margin_value, transactions = _load_sales_ytd()
    overstock = _calc_overstock_metrics(rows)
    transfer = _calc_transfer_acceptance()
    lost_qty = _calc_lost_sales(rows)

    avg_ticket = (sales_value / transactions) if transactions else 0
    margin_pct = (margin_value / sales_value * 100) if sales_value else 0

    today = datetime.now(BRT)
    days_into_year = today.timetuple().tm_yday
    sales_per_day = sales_value / days_into_year if days_into_year else 0

    # GMROII = (margem / custo_estoque_médio) — sem custo, usa proxy de unidades
    # GMROII inferido via stockTurn × margin% pra manter dimensional sense
    inventory_turn = (sales_value / overstock["totalStockUnits"]) if overstock["totalStockUnits"] else 0
    gmroii_pct = round(inventory_turn * margin_pct, 1)

    days_of_stock = (overstock["totalStockUnits"] / sales_per_day) if sales_per_day > 0 else 0

    kpis = {
        "salesYTD": {
            "value": round(sales_value, 2),
            "currency": "BRL",
            "transactions": transactions,
        },
        "marginYTD": {
            "value": round(margin_value, 2),
            "pct": round(margin_pct, 1),
            "currency": "BRL",
        },
        "gmroii": {
            "pct": gmroii_pct,
            "note": "margem% × giro estimado",
        },
        "inventoryTurn": {
            "ratio": round(inventory_turn, 2),
        },
        "daysOfStock": {
            "days": round(days_of_stock, 1),
        },
        "averageTicket": {
            "value": round(avg_ticket, 2),
        },
        "transferAcceptance": transfer,
        "lostSales": {
            "qtyEstimate": round(lost_qty, 0),
            "note": "≈ velocidade semanal de SKUs com cobertura < 1 sem",
        },
    }

    return save_report(
        "executive",
        [],
        endpoint="engine/executive.py",
        extra={
            "kpis": kpis,
            "overstock": overstock,
            "method": "agregação YTD do vendas_roi + replenishment-report + storepending",
            "asOf": datetime.now(BRT).isoformat(timespec="seconds"),
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("executive", run))
