# ADR-03: Slug canônico de loja derivado do nome Sisplan

**Status:** Aceito
**Data:** 2026-05-11
**Deciders:** Pati (Anselmi)

## Contexto

Existem 3 sistemas de identificação de lojas em uso paralelo:

1. **Sisplan** (fonte autoritativa de estoque/vendas): storeids numéricos
   `0101, 0102, ..., 0301` (30 IDs incluindo e-commerce e Marasquino)
2. **anselmi-pcp** (planejamento de produção): códigos curtos
   `BATEL, FARIA, JK, HIGI, BPOA, GMD, ALPH, ...` (18 lojas físicas)
3. **VM page** (interno): mistura — drills/plantas usam códigos curtos do PCP,
   estoques/vendas vêm do Sisplan via storeid

Sem normalização, `data/drills/<COD>.json` (formato PCP) não bate com
`storeid` do Sisplan → drill por loja quebrado.

## Decisão

Adotar **slug canônico** derivado do nome Sisplan limpo, com mapeamento explícito
em `data/loja_map.json`:

```
"0102" → "patio-batel"          (de "ANSELMI PÁTIO BATEL - PR")
"0103" → "porto-alegre"
"0104" → "faria-lima"
"0110" → "jk"
"0119" → "leblon"
...
"0101" → null  (e-commerce, sem planta física)
"0106" → null  (Centro Adm)
"0301-0302" → null  (Marasquino, marca diferente)
```

Formato do slug: lowercase-kebab, sem acentos, sem "ANSELMI" prefix nem UF suffix.

## Opções Consideradas

### A) Slug derivado do nome Sisplan (escolhida)
**Prós:** auto-documentado (`patio-batel` é claro), URL-safe, estável.
**Contras:** requer mapping JSON manual.

### B) Storeid Sisplan direto (`0102` em todos os lugares)
**Prós:** zero mapping, single source of truth.
**Contras:** ilegível ("0102.json" não diz nada), confunde devs e ops.

### C) Manter códigos curtos do PCP (`BATEL`, `JK`)
**Prós:** zero migration.
**Contras:** opacos pra quem não conhece a operação (o que é "BPOA"? Bourbon Porto Alegre? Barra POA?), 116 ocorrências hardcoded no `vm/index.html`.

### D) UUID
**Prós:** estável independente de rename de loja.
**Contras:** ilegível, exagero pra 18 entidades.

## Trade-offs

**Slug vs storeid Sisplan** — slug requer manutenção do `loja_map.json`
quando loja nova entra. Vale pra UX (drill mostra "patio-batel.jpg",
não "0102.jpg").

**Lojas Sisplan sem mapping (12 das 30)** — explicitamente `null` no map
(e-commerce, escritório, Marasquino, lojas novas sem planta). UI filtra
essas no `_buildLojasFromVar()`.

**Workflow renomeia automaticamente** — anselmi-pcp continua usando códigos
curtos. Workflow `sync_from_pcp.yml` traduz na chegada:
`data/drills/BATEL.json` (origem) → `data/drills/patio-batel.json` (destino).

## Consequências

- ✅ Drills carregam corretamente quando user seleciona loja Sisplan
- ✅ Slug é legível em URLs, logs, exports
- ✅ Workflow autoatualiza renames sem fricção humana
- ⚠️ Loja nova → editar `data/loja_map.json` manualmente
- ⚠️ Reorganização (ex: BPOA renomeado de "Barra POA" pra "Bourbon POA") →
  re-revisar o slug

## Ações

- [x] Criar `data/loja_map.json` com 30 entradas (18 slug + 12 null)
- [x] Patchar `vm-loader.js` pra carregar e expor `window.LOJA_MAP`
- [x] Patchar `_buildLojasFromVar` pra usar slug como `cod`, descartar null
- [x] Renomear 36 arquivos (`data/drills/*.json` + `data/plantas/*.jpg`)
- [x] Substituir 150+ ocorrências de códigos curtos no `vm/index.html`
- [x] Step de rename no workflow `sync_from_pcp.yml`
- [ ] Quando entrar loja nova, atualizar `loja_map.json` e re-rodar workflow
