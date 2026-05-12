# ADR-01: Sincronização anselmi-pcp → anselmi-roi via GitHub Actions

**Status:** Aceito
**Data:** 2026-05-11
**Deciders:** Pati (Anselmi)

## Contexto

O `anselmi-roi` (dashboard ROI clone + VM) precisa consumir vários arquivos
produzidos por pipelines no `anselmi-pcp` (repo privado):

- `ved_varejo.js` — dump Sisplan publicado pelo bot anselmi-pcp
- `data/cores_plm.json` — paleta PLM
- `data/oracle/*` — dumps Oracle (vw_giro_*, moa_vw_vitrine)
- `data/sisplan/vw_prod_info_roi.json`
- `data/plantas/*.jpg` + `data/drills/*.json`

Esses arquivos são atualizados a cada sync no `anselmi-pcp` (15min — 1h).
Sem mecanismo de sincronização, o `anselmi-roi` ficaria perpetuamente desatualizado.

## Decisão

GitHub Actions workflow `.github/workflows/sync_from_pcp.yml` no próprio
`anselmi-roi`, agendado a cada 30 min + dispatch manual, que:

1. Faz `actions/checkout@v4` do `anselmi-pcp` (privado) usando PAT `PCP_PAT`
   com permissão `Contents: Read-only` e `sparse-checkout` dos arquivos relevantes.
2. Copia/`rsync --delete` os arquivos pra `anselmi-roi/`.
3. Renomeia `data/drills/*.json` e `data/plantas/*.jpg` de códigos curtos
   (BATEL, JK, etc.) pros slugs canônicos (patio-batel, jk — ver ADR-03).
4. Roda `scripts/build_banco_fotos_v2.py` pra regenerar `data/banco_fotos.json`
   cruzando MOA_VW_VITRINE × Sisplan × Oracle.
5. Commita as mudanças se houver diff (autor: `github-actions[bot]`).
6. Push dispara o auto-deploy do Cloudflare Pages.

## Opções Consideradas

### A) GitHub Actions no anselmi-roi (escolhida)
| Dimensão | Avaliação |
|---|---|
| Complexidade | Baixa |
| Cost | Free (≤2k min/mês incluído) |
| Latência sync | ≤30 min |
| Team familiarity | Alta |

**Prós:** zero infra dedicada, log audível na Actions tab, retry manual fácil.
**Contras:** precisa PAT vivo (rotação 1×/ano), depende de GH availability.

### B) Workflow no anselmi-pcp empurra (cross-repo push)
**Prós:** sync imediato (não depende de cron).
**Contras:** mais setup (PAT do anselmi-roi precisa estar no anselmi-pcp), inverte direção
de dependência, anselmi-pcp passa a saber sobre anselmi-roi.

### C) Fetch em runtime (sem sync)
A página VM faz fetch direto do anselmi-pcp Cloudflare Pages.
**Prós:** sempre real-time.
**Contras:** depende do anselmi-pcp estar online, expõe anselmi-pcp publicamente, viola
isolamento de produção, sem caching trivial.

### D) Submodule Git
**Prós:** versionamento nativo.
**Contras:** submodule é PITA, anselmi-pcp tem 127MB (sparse não funciona com submodule),
contributor experience ruim.

## Trade-offs

**Latência aceitável** (até 30min de atraso vs anselmi-pcp): trabalho de VM/PCP é
operacional diário, não real-time. O ganho de isolamento (anselmi-roi roda
independentemente) compensa.

**PAT como dependência única**: mitigado pelo workflow `pat_expiry_check.yml` que
abre Issue 30 dias antes da expiração.

**[skip ci] no commit do bot**: removido após bug descoberto (Cloudflare Pages
honra a tag e não deployava as mudanças).

## Consequências

- ✅ `anselmi-roi` se atualiza sem ação humana
- ✅ Cloudflare Pages deploya automaticamente após cada sync
- ⚠️ Em caso de incidente no `anselmi-pcp`, anselmi-roi permanece operando com
  o último snapshot (graceful degradation)
- ⚠️ Adicionar arquivos novos pro sync exige editar `sparse-checkout` no workflow

## Ações

- [x] Implementar workflow
- [x] Criar PAT + secret PCP_PAT
- [x] Validar primeira sync (commit b7ac062)
- [x] Adicionar monitoring expiry (`pat_expiry_check.yml`)
- [ ] Considerar `workflow_run` event pra dispatch automático no anselmi-pcp
