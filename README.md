# anselmi-roi

Clone interno do ROI Volution (in-season retail analytics) para a Anselmi.

## URLs

- **Produção:** https://anselmi-roi.pages.dev (a configurar) ou subdomínio próprio (`roi.anselmi.com.br`)
- **Hospedagem:** Cloudflare Pages com auto-deploy via GitHub

## Como funciona

Frontend HTML/JS estático. Lê os JSONs sincronizados pelo pipeline do PCP (projeto separado) via URL pública:

- `https://anselmi-producao.pages.dev/data/sisplan/*.json`
- `https://anselmi-producao.pages.dev/data/oracle/*.json`
- `https://anselmi-producao.pages.dev/data/volution/*-report.json.gz`

CORS já está habilitado no projeto PCP (`access-control-allow-origin: *`).

## Estrutura

```
anselmi-roi/
├── index.html              ← landing / nav principal
├── reabastecimento.html    ← dashboard reabastecimento (com fotos)
├── excesso.html            ← dashboard excesso de estoque
├── transferencias.html     ← dashboard transferências
├── compras.html            ← dashboard compras
├── stock-quality.html      ← matriz Stock Quality
├── centro-empresa.html     ← KPIs executivos
├── alertas.html            ← alertas in-season
├── parametros.html         ← edição de parâmetros (Bloqueios, Cobertura, etc.)
├── lib/
│   ├── data-loader.js      ← fetch + decompress dos JSONs do PCP
│   └── foto-resolver.js    ← resolver de fotos (banco_fotos.json)
├── data/
│   └── banco_fotos.json    ← banco de fotos local (974 refs / 2.235 pares)
├── foto_map.json           ← overrides legados (3 casos: P39↔P09 etc.)
├── engine/                 ← scripts Python pra regenerar relatórios (uso futuro)
└── _headers                ← CORS + cache pra Cloudflare Pages
```

## Banco de fotos

Cobertura atual: **54,3%** (1.929 / 3.550 productids ativos do Sisplan).

URL pattern: `https://photo.anselmi.ind.br/cache/Fotos/{name}_1024.jpg` (ZenPhoto cache, 768×1024).

Pra regenerar o `data/banco_fotos.json`: rodar `python3 build_banco_fotos.py` no projeto `~/Documents/Claude/Projects/ROI/`. Requer JSONs sincronizados em `~/Documents/Claude/Projects/PCP 2/anselmi-pcp/data/sisplan/` e `data/oracle/`.

## Pendência

Liberação da view Oracle `MOA_VW_VITRINE` com EAN — sobe cobertura pra ~80% sem necessidade de overrides manuais. Texto formal em `~/Documents/Claude/Projects/ROI/PEDIDO_TI_MOA_VW_VITRINE.md`.

## Deploy

Push pra `main` → Cloudflare Pages atualiza em ~30s.

```bash
git add -A && git commit -m "descrição" && git push
```
