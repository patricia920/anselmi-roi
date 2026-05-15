# CLAUDE.md — Guia rápido do anselmi-roi

> Quem está chegando agora: este é o **ROI clone + VM** da Anselmi.
> Lê esse arquivo primeiro pra entender a topologia antes de mexer no código.

## O que é este repo

App estático (HTML + JS vanilla) servido por **Cloudflare Pages** que substitui o
ROI Volution interno da Anselmi. Adicionalmente hospeda o **Visual Merchandising**
(`/vm/`) que dá visibilidade da exposição física por loja.

**URL produção:** `anselmi-roi.pages.dev` (auth-gated, ver ADR-02).

## Topologia em 1 parágrafo

`anselmi-pcp` (privado, com pipelines Sisplan/Oracle/PLM) gera dumps de dados
toda hora. `anselmi-roi` puxa esses dumps via GitHub Actions a cada 30 min
(`sync_from_pcp.yml`), regenera `data/banco_fotos.json` (`build_banco_fotos_v2.py`),
commita e push. Cloudflare Pages auto-deploya. Equipe acessa via `/login` (senha
compartilhada, cookie HMAC). Estado de VM persiste em Cloudflare KV
(`VM_STATE_KV`) via Pages Function `/api/vm-state`.

## Estrutura

```
.
├── index.html                  # Home (Análises ROI)
├── alertas.html                # Alertas operacionais
├── compras.html                # Sugestão de compra
├── reabastecimento.html        # CD → lojas
├── excesso.html                # Sobra projetada
├── transferencias.html         # Loja → loja
├── stock-quality.html          # Matriz idade × cobertura
├── centro-empresa.html         # Executivo
├── parametros.html             # Parâmetros editáveis
├── vm/
│   ├── index.html              # Visual Merchandising (8.347 linhas)
│   └── vm-loader.js            # Carregador de globals (LOJA_MAP, COR_PLM, etc.)
│
├── lib/
│   ├── foto-resolver.js        # Resolve foto via banco_fotos (todas as HTMLs usam)
│   └── data-loader.js          # Helper pra JSONs gzipados
│
├── functions/                  # Cloudflare Pages Functions
│   ├── _middleware.js          # Auth gate (cookie HMAC, ver ADR-02)
│   ├── api/login.js            # POST /api/login (valida senha)
│   ├── api/logout.js
│   ├── api/params.js           # KV PARAMS_KV (parâmetros ROI)
│   └── api/vm-state.js         # KV VM_STATE_KV (estado VM por loja)
│
├── data/                       # Dados sincronizados do anselmi-pcp
│   ├── banco_fotos.json        # 1.875 refs (regen em cada sync)
│   ├── cores_plm.json          # 185 cores PLM (hex/nome)
│   ├── loja_map.json           # Storeid Sisplan → slug (ver ADR-03)
│   ├── gerentes.json           # Editável manual
│   ├── paleta_colecao.json     # Editável manual
│   ├── oracle/*.json           # Dumps Oracle (vw_giro_*, moa_vw_vitrine)
│   ├── sisplan/vw_prod_info_roi.json
│   ├── drills/<slug>.json      # Layout de cada loja física (18 arquivos)
│   └── plantas/<slug>.jpg      # Plantas técnicas (18 arquivos)
│
├── ved_varejo.js               # Dump Sisplan (8MB, publicado pelo bot anselmi-pcp)
│
├── scripts/
│   └── build_banco_fotos_v2.py # Regenera banco_fotos.json (auto-rodado no sync)
│
├── .github/workflows/
│   ├── sync_from_pcp.yml       # Sync 30/30min do anselmi-pcp (ver ADR-01)
│   ├── pat_expiry_check.yml    # Alerta 30d antes do PAT expirar
│   └── e2e.yml                 # Smoke E2E Playwright em push + cron diário
│
├── tests/
│   └── vm.smoke.spec.js        # 8 specs E2E
│
├── docs/adr/
│   ├── ADR-01-sync-via-github-actions.md
│   ├── ADR-02-auth-hmac-custom.md
│   └── ADR-03-slugs-sisplan.md
│
├── wrangler.toml               # Config CF Pages (KV bindings)
└── _headers                    # Cache rules CF Pages
```

## Decisões importantes

- **ADR-01** — Como o anselmi-pcp alimenta o anselmi-roi
- **ADR-02** — Por que auth com cookie HMAC custom
- **ADR-03** — Por que slug Sisplan e não storeid

## Quem mantém o quê

| Recurso | Origem | Como atualizar |
|---|---|---|
| Estoque, vendas, lojas | Sisplan via `ved_varejo.js` | Bot do anselmi-pcp publica, sync puxa |
| Cores PLM (hex) | `data/cores_plm.json` | anselmi-pcp `data/cores_plm.json` |
| Fotos das peças | `data/banco_fotos.json` | Regen automática a cada sync |
| Plantas das lojas | `data/plantas/<slug>.jpg` | anselmi-pcp `data/plantas/<COD>.jpg` (rename automático) |
| Drills das lojas | `data/drills/<slug>.json` | anselmi-pcp `data/drills/<COD>.json` |
| Mapeamento storeid→slug | `data/loja_map.json` | **Manual** — quando loja nova entra |
| Paleta da coleção | `data/paleta_colecao.json` | **Manual** — a cada virada de coleção |
| Gerentes | `data/gerentes.json` | **Manual** — PR no repo |

## Variáveis de ambiente (Cloudflare Pages)

| Var | Pra que serve | Onde setar |
|---|---|---|
| `SHARED_PASSWORD` | Senha do `/login` | CF Pages → Settings → Env vars |
| `AUTH_SECRET` | Secret HMAC do cookie de sessão | idem |
| `PARAMS_KV` | KV binding pra `/api/params` | CF Pages → Settings → Functions → KV |
| `VM_STATE_KV` | KV binding pra `/api/vm-state` | idem |

## Secrets do GitHub Actions

| Secret | Pra que serve |
|---|---|
| `PCP_PAT` | Fine-grained PAT com `Contents: Read` no `patricia920/anselmi-pcp`. Expira 10/05/2027. Renove via workflow `pat_expiry_check.yml`. |
| `VM_TEST_PASSWORD` | Senha pro E2E logar via `/api/login` |

## Rodando localmente

```bash
# Servir o site
npx wrangler pages dev .

# Rodar E2E (precisa VM_TEST_PASSWORD)
export VM_TEST_PASSWORD='<senha>'
npm run test:e2e

# Regenerar banco_fotos manualmente
python3 scripts/build_banco_fotos_v2.py
```

## Workflows

| Workflow | Quando roda | O que faz |
|---|---|---|
| `sync_from_pcp.yml` | A cada 30min + manual | Puxa dumps + renomeia slugs + regen banco_fotos + commita |
| `pat_expiry_check.yml` | Toda 2ª feira 08:00 UTC | Abre Issue se PAT expira ≤30d |
| `e2e.yml` | Push em paths críticos + cron diário 12:00 UTC | Smoke E2E contra produção |

## Onde achar coisas no anselmi-pcp

```
patricia920/anselmi-pcp/
├── ved_varejo.js                              # Sisplan dump publicado pelo bot
├── data/
│   ├── cores_plm.json
│   ├── oracle/
│   │   ├── vw_giro_estoque.json
│   │   ├── vw_giro_costura.json
│   │   ├── vw_giro_venda.json.gz
│   │   └── moa_vw_vitrine.json                # Catálogo de fotos (98.871 linhas)
│   ├── sisplan/vw_prod_info_roi.json          # Ref × cor × descrição
│   ├── plantas/<COD_CURTO>.jpg                # BATEL.jpg, JK.jpg, etc.
│   └── drills/<COD_CURTO>.json
└── functions/api/vm-state.js                   # Versão "irmã" da nossa /api/vm-state
```

## Troubleshooting comum

**Foto não aparece pra ref X** → `python3 scripts/build_banco_fotos_v2.py` + ver `data/banco_fotos_pendencias.csv` pro motivo (`ref_nao_existe`, `sem_match`, etc.).

**Sync falha com `Bad credentials`** → PAT `PCP_PAT` expirou ou foi revogado. Regenera e atualiza secret.

**`/api/vm-state` retorna 500 "KV não configurado"** → KV binding `VM_STATE_KV` não está bindado no Pages project. Settings → Functions → KV bindings.

**Loja Sisplan aparece sem drill** → não tem entrada no `data/loja_map.json` (slug é `null` → filtrada pelo `_buildLojasFromVar`). Adicione mapping + crie `data/drills/<slug>.json`.

**Tests E2E falham com 401 "Senha inválida"** → `VM_TEST_PASSWORD` está errada ou não setada.

## Stack

- Frontend: HTML5 + JS vanilla (sem framework — performance + simplicidade de deploy)
- Hosting: Cloudflare Pages (free tier suficiente)
- Functions: Cloudflare Pages Functions (Workers runtime, JS)
- Storage: Cloudflare KV (2 namespaces — PARAMS_KV, VM_STATE_KV)
- CI/CD: GitHub Actions
- Tests: Playwright (E2E)
- Build script: Python 3.10+

---

## Estado em 15/05/2026 — 100% Sisplan-real

**Todas as ~20 telas operacionais agora usam dados reais Sisplan + drill. Zero mock restante em produção.**

### Funções helper centrais (em `vm/index.html`)

Todas seguem o contrato `_computeX(cod)` onde `cod` é storeid Sisplan (`0102`) ou `'*'` (consolidado):

- `_computeRankingAuto(cod)` → `{cores[], pecas[]}` — top peças/cores expostas no drill
- `_computeParadas(cod)` → `{saudavel, recente, atencao, encalhada, zumbi, lista[]}` — 5 status por (ref × loja). Critério encalhada: chegou há ≥6m loja + ≥4m sem vender. "Chegou" = primeira venda Sisplan (proxy)
- `_computeBuracos(cod)` → `[]` — refs com estoque + venda mas sem VM (cruza `VAR_ESTOQUE_LOJA` + `VAR_VENDAS_LOJA_2026` + drill)
- `_computeCDLotado(threshold)` → `[]` — `vw_giro_estoque` cta=CD com qty ≥ threshold, agrupado por ref+cor
- `_computeCoresPerformance(cod)` → `[]` — VM% (drill) vs Venda% (`VAR_VENDAS_LOJA_2026`) por cor + hex COR_PLM
- `_computeMixCategoria(cod)` → `[]` — VM% vs Venda% vs Estoque% por tipo
- `_computeCenarios(cod)` → `{buraco, parado, repor, sucesso}` — 4 cenários unificados pra Matriz cruzada

### Helpers de UI / fluxo

- `_slugToStoreid(slug)` — inverte LOJA_MAP `{storeid: slug}` → `{slug: storeid}`
- `_nomeLoja(slug)` — nome amigável da loja a partir de LOJAS
- `_loadDrillData(slug)` — fetch + cache `data/drills/<slug>.json`
- `_lookupRef(ref)` / `lookupRef(r)` — tolera ref 5d e 6d (zero-pad)
- `_historiaVendaRefLoja(ref, storeid)` — extrai `{primeira, ultima, idade_meses, parada_meses, total}` de VAR_VENDAS_LOJA_DATA
- `pieceImage(p)` / `_resolvePhoto(p)` — cascade: cor exata → any color → silhueta. Ver detalhe abaixo.

### Mapa telas → funções

| Tela (menu) | Função render | Helpers usados |
|---|---|---|
| Drill por loja | `renderAraras`, `loadDrillForLoja` | `data/drills/<slug>.json` |
| Planta da loja | `renderPlantaHTML`, `renderPlanta` | `data/plantas/<slug>.jpg/svg` |
| Estoque CD | `renderEstoqueCD` | `VAR_ESTOQUE` |
| Estoque Lojas | `renderEstoqueLojas` | `VAR_ESTOQUE_LOJA` |
| Vendas Loja | `renderVendasLoja` | `VAR_VENDAS_LOJA_2026` |
| Buracos no VM | `renderBuracos` | `_computeBuracos` |
| Estoque alto CD | `renderCD` | `_computeCDLotado` |
| Performance cor | `renderCores` | `_computeCoresPerformance` |
| Paradas no VM (05) | `renderParadas` | `_computeParadas` (mosaic-grid `#paradas-grid`) |
| Matriz cruzada | `renderMatrix` → `renderCenarioActive` | `_computeCenarios` (cache `_CEN_DATA_CACHE`) |
| Mix categoria | `renderMix` | `_computeMixCategoria` |
| Ranking + Vendas×Exposição | `renderRanking` + `renderParadasVendas` | `_computeRankingAuto` + `_computeParadas` |
| Otimizar VM | `renderOtimizar` → `gerarSugestoesLoja` | `_computeParadas` (SAI) + `_computeBuracos` (ENTRA) |
| Hoje · cmd | `renderHoje` | `_computeBuracos` + `_computeParadas` + `_computeCDLotado` |
| Alerts banner | `renderAlerts` | top de cada cenário |
| Looks quebrados | `renderLooks` | `VAR_ESTOQUE_LOJA` (estoque=0 = ruptura) |

### Bug raiz #1 — REF_INDEX tinha 2 entradas pra mesma ref

Mock no HTML cadastra refs em `'28871'` (5d). Sisplan vem em `'028871'` (6d zero-pad). Mock tinha cadastros errados (`'28871': {tipo:'Capa', cor:'Off Camelo'}` quando Sisplan diz `'028871': {tipo:'Básica', corPrincipal:'001'}`).

Fix em `vm/vm-loader.js`: o merge do `ref_index_sisplan.json` agora propaga override pras DUAS chaves (5d **e** 6d). Sem isso, lookup de 5d retornava mock errado.

### Bug raiz #2 — `_resolvePhoto` sempre caía em qualquer cor

Antes pegava `getFotoAnyColor()` (primeira cor do banco) antes de tentar a cor específica. Resultado: peça preta mostrava foto roxa.

Fix em `vm/index.html::_resolvePhoto`: tenta cor específica via `getFotosByRefColor(ref, p.corPrincipal)` primeiro; se vazio, fallback `getFotoAnyColor`.

### Bug raiz #3 — formato de cor Oracle vs Sisplan

`vw_giro_estoque` traz cor como `*10` (Oracle). `banco_fotos.json` usa `010` (Sisplan zero-pad).

Fix em `lib/foto-resolver.js::getFotosByRefColor`: nova função `_normCor` normaliza:
- `*10` → `010`
- `10` → `010` (zero-pad)
- `C25`, `A98` etc → mantém

### Bug raiz #4 — URLs no banco_fotos retornam 404

Build script extraiu nomes do `MOA_VW_VITRINE` (catálogo Oracle), mas alguns arquivos foram renomeados/removidos no Zenphoto. Ex: `28871_10_1024.jpg` é 404 mesmo a chave `010` existindo no JSON.

Fix em `vm/index.html::_resolvePhoto`: cadeia onerror — `cor exata 404 → tenta any color → silhueta`. Mantém peça visível mesmo quando a cor pedida não tem foto.

### Status da senha

`SHARED_PASSWORD` (Cloudflare Pages) foi resetada pra `123456` em 15/05. **Trocar pra algo forte quando prático** — `123456` é só pra desbloqueio rápido pós-perda da senha original.

### Resíduo (próxima sessão)

- Botões "Aprovar/Recusar" no Otimizar VM ainda chamam `alert()` → falta gravar no KV state (audit log)
- Log de atividade no Hoje é placeholder → falta ler do KV
- 73 refs do `refs_sem_foto_v2.csv` precisam ser fotografadas pelo studio
- Script de limpeza do `banco_fotos.json`: rodar HEAD em cada URL, marcar 404, regenerar só com URLs válidas

### Commits chave dessa sessão (15/05/2026)

- `ccbcd06` — Otimizar VM (última tela mock migrada)
- `1a4998d` — Onda 3 (Alerts + Hoje + Looks)
- `cd49aac` — Cascade onerror das fotos
- `a2587c9` — Normalização cor Oracle → Sisplan no foto-resolver
- `4075f07` — vm-loader propaga Sisplan override pras 2 chaves
- `37c5932` — Onda 1+2 (Buracos + CD + Cores + Mix + Matriz)
- `2fbf400` — Detector Vendas × Exposição na Análise & Cobertura
- `8b5e971` — padStart 6 dig no lookup REF_INDEX
