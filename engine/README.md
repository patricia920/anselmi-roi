# roi/engine — Motores de cálculo do clone ROI Volution

Cada script gera um `data/volution/*-report.json.gz` consumido pelas telas do
MVP em `roi/*.html`.

## Motores

| Script | Output | Tela do MVP | Fonte primária |
|---|---|---|---|
| `overstock.py` | `overstock-report.json.gz` | `excesso.html` | replenishment-report + custo unit |
| `transfers.py` | `transfers-report.json.gz` | `transferencias.html` | replenishment-report (pointsOfSaleRanking) |
| `purchases.py` | `purchases-report.json.gz` | `compras.html` | replenishment + sisplan/wh_stock + bloqueios |
| `stock_quality.py` | `stock-quality-report.json.gz` | `stock-quality.html` | replenishment + sisplan/stock_mov_roi |
| `alerts.py` | `alerts-report.json.gz` | `alertas.html` | replenishment + params Anselmi |
| `executive.py` | `executive-report.json.gz` | `centro-empresa.html` | sisplan/vendas_roi + replenishment + storepending |
| `params_io.py` | `params-state.json` (não-gz) | `parametros.html` | static + edição via /api/edit-file |

## Helpers compartilhados

`_common.py`:

- `load_sisplan(view)`, `load_oracle(view)`, `load_volution(name)`
- `replenishment_rows()` — atalho pro `replenishment-report.json.gz`
- `get_expr(row, key)`, `get_code(row)`, `get_desc(row)` — extrai do schema Volution
- `save_report(name, rows, ...)` — escreve `data/volution/{name}-report.json.gz`
- `cli_main(name, run_fn)` — envelope CLI uniforme

## Dados estáticos

`engine/data/`:

- `params_anselmi.json` — snapshot 06/05/2026 dos parâmetros capturados do ROI
  Volution (11 bloqueios, 25 estoque mínimo, 6 sazonalidades, cobertura padrão).
- `seasonal_curve.json` — curva 53 semanas validada.

## Como rodar local

```bash
# Pré-requisito: estar dentro do anselmi-pcp clone
cd ~/Documents/Claude/Projects/PCP\ 2/anselmi-pcp

# Bootstrap inicial dos parâmetros (só na primeira vez)
python3 roi/engine/params_io.py --bootstrap

# Rodar 1 motor (dry-run não escreve nada)
python3 roi/engine/overstock.py --dry-run

# Rodar todos os 6 motores que dependem de replenishment-report
for m in overstock transfers purchases stock_quality alerts executive; do
  python3 "roi/engine/$m.py"
done
```

## Como rodar no CI

O workflow `.github/workflows/compute_roi.yml` encadeia os 6 motores depois
que `sync_volution`, `sync_sisplan` e `query_oracle` terminam. Self-hosted
runner `server_scruffy` (mesma máquina dos outros syncs).

## Fórmulas validadas

Documentadas em `06_algoritmos_inferidos.md` no projeto local da Pati. Cada
motor cita a seção relevante no docstring do arquivo.
