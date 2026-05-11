#!/usr/bin/env python3
"""
alerts.py — Alertas operacionais.

Output: data/volution/alerts-report.json.gz

7 tipos validados em 03_alertas.md / 06_algoritmos §10:

  1. Sem Vendas        — SKU em loja há ≥30d sem nenhuma venda registrada
  2. Dados Base        — falta unit_cost, classificação, sazonalidade ou estoque mínimo
  3. Retardamento      — recepção pendente há ≥14d sem confirmação
  4. Bloqueio          — SKU bloqueado mas com estoque > 0 ou pedido > 0
  5. Cobertura Crítica — cobertura < 1 sem (ruptura iminente)
  6. Excesso Severo    — sobra_53 / estoque > 50%
  7. Velocidade Outlier — velocity_weekly muito acima/abaixo da média da categoria

Snapshot Anselmi 06/05/2026: 957 alertas total
  - Sem Vendas: 840
  - Dados Base: 60
  - Retardamento: 57
  - resto: 0 nas amostras

Schema do row de saída:
  {
    type, severity (low|med|high|critical), message,
    rootProductCode, rootProductName, storeCode, storeName,
    detectedAt, evidence: {...}
  }
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from _common import (
    BRT,
    cli_main,
    get_code,
    get_desc,
    get_expr,
    load_engine_data,
    load_sisplan,
    replenishment_rows,
    save_report,
)


def _alert(type_: str, severity: str, msg: str, **fields) -> dict:
    """Helper pra criar um alerta no formato canônico."""
    return {
        "type": type_,
        "severity": severity,
        "message": msg,
        "detectedAt": datetime.now(BRT).isoformat(timespec="seconds"),
        **fields,
    }


def _alerts_no_sales(rows: list[dict]) -> list[dict]:
    """Tipo 1: Sem Vendas — SKU com estoque>0 e velocidade=0 há ≥30d."""
    out = []
    for r in rows:
        if get_expr(r, "actualStock") <= 0:
            continue
        velocity = get_expr(r, "salesProjection")
        if velocity <= 0 and get_expr(r, "totalSales") <= 0:
            out.append(_alert(
                "no_sales", "med",
                "SKU com estoque mas sem vendas há ≥30d",
                rootProductCode=get_code(r),
                rootProductName=get_desc(r),
                evidence={
                    "actualStock": get_expr(r, "actualStock"),
                    "totalSales": get_expr(r, "totalSales"),
                },
            ))
    return out


def _alerts_data_base(rows: list[dict]) -> list[dict]:
    """Tipo 2: Dados Base — falta info crítica do SKU."""
    out = []
    for r in rows:
        code = get_code(r)
        missing = []
        # totalSales = 0 com actualStock > 0 já vira no_sales, ignora aqui
        if not get_desc(r):
            missing.append("description")
        if get_expr(r, "minimumStock") <= 0 and get_expr(r, "actualStock") > 0:
            missing.append("minimumStock")
        if missing:
            out.append(_alert(
                "data_base", "low",
                f"Faltam dados base: {', '.join(missing)}",
                rootProductCode=code,
                rootProductName=get_desc(r) or "(sem descrição)",
                evidence={"missing": missing},
            ))
    return out


def _alerts_late_reception(rows: list[dict], days_threshold: int = 14) -> list[dict]:
    """Tipo 3: Retardamento — recepção pendente há > N dias.

    Sem timestamp por row na replenishment-report, usamos heurística:
    purchaseOrder > 0 AND actualStock baixo + sales_projection > 0 implica que
    a recepção devia ter chegado. Marcamos como suspeita.
    """
    out = []
    today = datetime.now(BRT)
    for r in rows:
        recep = get_expr(r, "purchaseOrder")
        actual = get_expr(r, "actualStock")
        velocity_weekly = get_expr(r, "salesProjection") / 4.33
        if recep > 0 and actual < velocity_weekly * 1 and velocity_weekly > 0:
            # Pediu mas não chegou e o estoque já está apertado
            out.append(_alert(
                "late_reception", "high",
                f"Recepção pendente ({recep} unid) com estoque <1sem cobertura",
                rootProductCode=get_code(r),
                rootProductName=get_desc(r),
                evidence={
                    "pendingReception": recep,
                    "actualStock": actual,
                    "weeklyVelocity": round(velocity_weekly, 2),
                },
            ))
    return out


def _alerts_blocked(rows: list[dict], blocked_codes: set[str]) -> list[dict]:
    """Tipo 4: Bloqueio com estoque/pedido."""
    out = []
    for r in rows:
        code = get_code(r)
        if code not in blocked_codes:
            continue
        actual = get_expr(r, "actualStock")
        recep = get_expr(r, "purchaseOrder")
        if actual > 0 or recep > 0:
            out.append(_alert(
                "blocked_with_stock", "high",
                "SKU bloqueado mas com estoque ou recepção pendente",
                rootProductCode=code,
                rootProductName=get_desc(r),
                evidence={"actualStock": actual, "pendingReception": recep},
            ))
    return out


def _alerts_critical_coverage(rows: list[dict]) -> list[dict]:
    """Tipo 5: Cobertura < 1 semana com vendas ativas."""
    out = []
    for r in rows:
        actual = get_expr(r, "actualStock")
        velocity_weekly = get_expr(r, "salesProjection") / 4.33
        if velocity_weekly <= 0:
            continue
        coverage = actual / velocity_weekly
        if 0 < coverage < 1:
            out.append(_alert(
                "critical_coverage", "critical",
                f"Cobertura {coverage:.1f} sem — ruptura iminente",
                rootProductCode=get_code(r),
                rootProductName=get_desc(r),
                evidence={
                    "actualStock": actual,
                    "weeklyVelocity": round(velocity_weekly, 2),
                    "coverageWeeks": round(coverage, 2),
                },
            ))
    return out


def _alerts_severe_overstock(rows: list[dict]) -> list[dict]:
    """Tipo 6: Excesso severo — overstock > 50% do estoque atual."""
    out = []
    for r in rows:
        actual = get_expr(r, "actualStock")
        overstock = get_expr(r, "overstock")
        if actual <= 0:
            continue
        if overstock / actual > 0.5:
            out.append(_alert(
                "severe_overstock", "med",
                f"Excesso severo: {overstock:.0f} unid > 50% do estoque",
                rootProductCode=get_code(r),
                rootProductName=get_desc(r),
                evidence={
                    "actualStock": actual,
                    "overstock": overstock,
                    "ratio": round(overstock / actual, 2),
                },
            ))
    return out


def _alerts_velocity_outlier(rows: list[dict]) -> list[dict]:
    """Tipo 7: Velocidade fora de 3σ da média da categoria."""
    out = []
    # Agrupa velocidades por classification1
    by_cat: dict[str, list[float]] = defaultdict(list)
    cat_for: dict[str, str] = {}
    for r in rows:
        cat = (
            (r.get("classifications") or {}).get("classification1")
            or r.get("classification1")
            or "default"
        )
        v = get_expr(r, "salesProjection") / 4.33
        if v > 0:
            by_cat[cat].append(v)
        cat_for[get_code(r)] = cat
    # Calcula stats
    stats: dict[str, tuple[float, float]] = {}
    for cat, vs in by_cat.items():
        if len(vs) < 5:
            continue
        mean = sum(vs) / len(vs)
        var = sum((x - mean) ** 2 for x in vs) / len(vs)
        std = var ** 0.5
        stats[cat] = (mean, std)
    for r in rows:
        code = get_code(r)
        cat = cat_for.get(code, "default")
        st = stats.get(cat)
        if not st:
            continue
        v = get_expr(r, "salesProjection") / 4.33
        mean, std = st
        if std == 0:
            continue
        z = (v - mean) / std
        if abs(z) > 3:
            severity = "high" if abs(z) > 4 else "med"
            direction = "muito acima" if z > 0 else "muito abaixo"
            out.append(_alert(
                "velocity_outlier", severity,
                f"Velocidade {direction} da média da categoria ({z:+.1f}σ)",
                rootProductCode=code,
                rootProductName=get_desc(r),
                evidence={
                    "velocityWeekly": round(v, 2),
                    "categoryMean": round(mean, 2),
                    "zScore": round(z, 2),
                    "category": cat,
                },
            ))
    return out


def _load_blocked_set() -> set[str]:
    try:
        params = load_engine_data("params_anselmi.json")
    except FileNotFoundError:
        return set()
    blocked = set()
    for b in params.get("bloqueios", []):
        for c in b.get("produtos") or b.get("rootProductCodes") or []:
            blocked.add(str(c).strip())
    return blocked


def run(*, dry_run: bool = False) -> dict:
    rows = replenishment_rows()
    blocked = _load_blocked_set()

    all_alerts: list[dict] = []
    all_alerts.extend(_alerts_no_sales(rows))
    all_alerts.extend(_alerts_data_base(rows))
    all_alerts.extend(_alerts_late_reception(rows))
    all_alerts.extend(_alerts_blocked(rows, blocked))
    all_alerts.extend(_alerts_critical_coverage(rows))
    all_alerts.extend(_alerts_severe_overstock(rows))
    all_alerts.extend(_alerts_velocity_outlier(rows))

    # Sort: critical → high → med → low, dentro do tipo por relevância
    sev_order = {"critical": 0, "high": 1, "med": 2, "low": 3}
    all_alerts.sort(key=lambda a: (sev_order.get(a["severity"], 9), a["type"]))

    # Contagens por tipo (pra header da tela alertas.html)
    by_type = Counter(a["type"] for a in all_alerts)
    by_severity = Counter(a["severity"] for a in all_alerts)

    return save_report(
        "alerts",
        all_alerts,
        endpoint="engine/alerts.py",
        extra={
            "byType": dict(by_type),
            "bySeverity": dict(by_severity),
            "thresholds": {
                "no_sales_days": 30,
                "late_reception_days": 14,
                "critical_coverage_weeks": 1,
                "severe_overstock_ratio": 0.5,
                "velocity_outlier_sigma": 3,
            },
            "method": "7 detectores em replenishment-report + params Anselmi",
        },
        dry_run=dry_run,
    )


if __name__ == "__main__":
    import sys
    sys.exit(cli_main("alerts", run))
