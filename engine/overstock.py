#!/usr/bin/env python3
"""
overstock.py — Relatório de Excesso de estoque.

Output: data/volution/overstock-report.json.gz

Fórmulas validadas em 06_algoritmos_inferidos.md §11:

  Sobra horizonte H (semanas) = max(0, EA + RP_loja + RP_dep − Σ projeção_t [t=1..H])
  Custo horizonte H = Sobra_H × custo_unitário
  projeção_t = vendas_velocidade × peso_sazonal[semana_atual + t]   (curva 53 sem)

Fonte primária: data/volution/replenishment-report.json.gz (já tem totalSales,
salesProjection, actualStock, expressions). Como o motor Volution já calculou
salesProjection com curva sazonal, usamos isso como base e replicamos pra
horizontes 12/28/53 sem.

Schema do row de saída (paridade com a tela excesso.html do MVP):
  {
    rootProductCode, rootProductName,
    storeCode, storeName,                # Σ por loja
    actualStock, recepLoja, recepDep,
    sobra12, sobra28, sobra53,
    custo12, custo28, custo53,
    salesVelocity, weeksToZero,
    classification1, classification2,    # categoria/marca
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


# Horizontes do ROI (semanas). 12 = curto; 28 = médio (≈ estação); 53 = ciclo anual.
HORIZONS = (12, 28, 53)


def _seasonal_weights(curve: list[float], from_week: int = 1) -> list[float]:
    """Retorna 53 pesos normalizados a partir da curva (soma = 1.0).

    A curva crua tem 53 valores absolutos por semana; aqui normalizamos pra
    distribuir vendas projetadas anualmente entre as semanas.
    """
    if not curve:
        # Fallback: uniforme
        return [1 / 53] * 53
    total = sum(curve) or 1.0
    return [v / total for v in curve]


def _project_sales(sales_velocity_weekly: float, weights: list[float], horizon: int) -> float:
    """Projeção de vendas em 'horizon' semanas a partir da semana atual.

    Como salesProjection do Volution já vem com curva sazonal aplicada,
    reescalamos pelo total dos pesos das próximas H semanas.
    """
    if horizon <= 0:
        return 0.0
    if horizon >= len(weights):
        return sales_velocity_weekly * horizon  # ciclo completo, escala linear
    # Pesa H semanas adjacentes (sem âncora de calendário aqui — usamos head)
    avg_weight = sum(weights[:horizon]) / horizon
    return sales_velocity_weekly * horizon * (avg_weight * 53)


def _load_unit_cost_map() -> dict[str, float]:
    """Lê data/sisplan/vw_prod_info_roi.json e mapeia productCode → custo unit.

    O Sisplan não exporta custo direto na vw_prod_info_roi (só productid,
    rootproductid, color, size, description, classifications). Custo vem de
    outra fonte (Sisplan produto_001.json ou Oracle vw_giro_estoque). Tentamos
    ambos com fallback gracioso.
    """
    try:
        prod = load_sisplan("produto_001")
        cost: dict[str, float] = {}
        rows = prod if isinstance(prod, list) else (prod.get("rows") or prod.get("data") or [])
        for r in rows:
            code = r.get("rootproductcode") or r.get("productcode") or r.get("code")
            cu = r.get("unit_cost") or r.get("custo_unit") or r.get("custounit")
            if code and cu is not None:
                try:
                    cost[str(code).strip()] = float(cu)
                except (TypeError, ValueError):
                    pass
        if cost:
            return cost
    except FileNotFoundError:
        pass
    # Fallback Oracle: vw_giro_estoque tem valor_estoque e qtd, derivamos custo médio
    try:
        oracle = __import__("_common").load_oracle("vw_giro_estoque")
        cost = {}
        rows = oracle if isinstance(oracle, list) else (oracle.get("rows") or [])
        for r in rows:
            code = r.get("rootproductcode") or r.get("productcode") or r.get("CODIGO")
            qtd = r.get("qtd") or r.get("QTD") or r.get("quantidade") or 0
            valor = r.get("valor") or r.get("VALOR") or r.get("valor_estoque") or 0
            try:
                qtd_n = float(qtd)
                valor_n = float(valor)
                if code and qtd_n > 0:
                    cost[str(code).strip()] = valor_n / qtd_n
            except (TypeError, ValueError):
                pass
        return cost
    except FileNotFoundError:
        return {}


def run(*, dry_run: bool = False) -> dict:
    # Carrega curva sazonal (53 pesos)
    try:
        curve_data = load_engine_data("seasonal_curve.json")
        curve = (
            curve_data.get("weights")
            or curve_data.get("curve")
            or (curve_data if isinstance(curve_data, list) else [])
        )
    except FileNotFoundError:
        curve = []
    weights = _seasonal_weights(curve)

    # Carrega fonte primária: replenishment-report (motor Volution)
    base_rows = replenishment_rows()

    # Custos unitários por SKU
    unit_cost = _load_unit_cost_map()

    out_rows: list[dict] = []
    for r in base_rows:
        actual_stock = get_expr(r, "actualStock")
        sales_proj = get_expr(r, "salesProjection")  # já vem com sazonalidade do Volution
        total_sales = get_expr(r, "totalSales")
        recep = get_expr(r, "purchaseOrder")  # estimativa de recepção pendente

        # Velocidade média semanal: se Volution já entregou salesProjection,
        # usamos como referência mensal e dividimos por 4.33 → semanal.
        sales_velocity_weekly = (sales_proj / 4.33) if sales_proj else (total_sales / 4.33 if total_sales else 0.0)

        sobra: dict[int, float] = {}
        custo: dict[int, float] = {}
        code = get_code(r)
        cu = unit_cost.get(code, 0.0)
        for h in HORIZONS:
            proj = _project_sales(sales_velocity_weekly, weights, h)
            s = max(0.0, actual_stock + recep - proj)
            sobra[h] = round(s, 2)
            custo[h] = round(s * cu, 2)

        weeks_to_zero = (actual_stock / sales_velocity_weekly) if sales_velocity_weekly > 0 else 999

        out_rows.append({
            "rootProductCode": code,
            "rootProductName": get_desc(r),
            "actualStock": actual_stock,
            "purchaseOrder": recep,
            "salesProjection": round(sales_proj, 2),
            "salesVelocityWeekly": round(sales_velocity_weekly, 3),
            "weeksToZero": round(weeks_to_zero, 1),
            "sobra12": sobra[12],
            "sobra28": sobra[28],
            "sobra53": sobra[53],
            "custo12": custo[12],
            "custo28": custo[28],
            "custo53": custo[53],
            "unitCost": round(cu, 2),
        })

    # Sort por custo12 desc (mais excesso projetado primeiro)
    out_rows.sort(key=lambda x: x.get("custo12", 0), reverse=True)

    return save_report(
        "overstock",
        out_rows,
        endpoint="engine/overstock.py",
        extra={
            "horizons_weeks": list(HORIZONS),
            "method": "actualStock + recep - Σ(velocity × seasonal_weights)",
            "source": "data/volution/replenishment-report.json.gz",
            "unit_cost_source": "data/sisplan/produto_001.json (fallback: oracle/vw_giro_estoque)",
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("overstock", run))
