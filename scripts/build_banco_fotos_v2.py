"""
build_banco_fotos_v2.py
========================
Versão automatizada do build_banco_fotos — usa MOA_VW_VITRINE (Sisplan) em vez
do XLSX manual de acervo.

Inputs (vêm via sync_from_pcp.yml):
  data/oracle/vw_giro_estoque.json
  data/oracle/vw_giro_costura.json
  data/oracle/vw_giro_venda.json.gz
  data/oracle/moa_vw_vitrine.json           ← NOVO (98.871 fotos catalogadas)
  data/sisplan/vw_prod_info_roi.json

Output:
  data/banco_fotos.json (substitui o atual em produção)
  data/banco_fotos_pendencias.csv (refs sem match)

Diferenças vs v1:
  - Sem dependência de XLSX manual
  - 98.871 linhas em vez de 6.997
  - cor_arquivo já vem com formato '*01 - COR UM' do Sisplan
  - Auto-roda em cada sync_from_pcp.yml
"""
import json, gzip, collections, re, csv, sys
from pathlib import Path

REPO = Path(__file__).parent.parent
DATA = REPO / 'data'

# ---------- 1) Carrega views Oracle ----------
oracle = collections.defaultdict(set)
def load_oracle(rows):
    for r in rows:
        cd = str(r.get('cd_item', '')).strip()
        cor = str(r.get('cor', '')).strip()
        if cd and cor:
            oracle[cd].add(cor)

for f in ['oracle/vw_giro_estoque.json', 'oracle/vw_giro_costura.json']:
    p = DATA / f
    if p.exists():
        with open(p) as fp: load_oracle(json.load(fp).get('rows', []))

vg = DATA / 'oracle/vw_giro_venda.json.gz'
if vg.exists():
    with gzip.open(vg, 'rt') as f: load_oracle(json.load(f).get('rows', []))

# ---------- 2) Carrega Sisplan ----------
sisplan = collections.defaultdict(set)
sisplan_meta = collections.defaultdict(dict)
sp = DATA / 'sisplan/vw_prod_info_roi.json'
if sp.exists():
    with open(sp) as f:
        for r in json.load(f).get('rows', []):
            ref = str(r.get('rootproductid', '')).strip()
            c = str(r.get('color', '')).strip()
            if ref and c:
                sisplan[ref].add(c)
                sisplan_meta[ref][c] = {
                    'description': r.get('description'),
                    'classification1': r.get('classification1'),
                }

print(f'Oracle refs: {len(oracle)}  |  Sisplan refs: {len(sisplan)}')

# ---------- 3) Constrói mapa cor_oracle → color_sisplan por ref ----------
ora_to_sis = {}
for ref in (set(oracle) | set(sisplan)):
    o_set, s_set = oracle.get(ref, set()), sisplan.get(ref, set())
    pairs, o_used, s_used = {}, set(), set()

    # TIER 1: match exato
    for c in o_set & s_set:
        pairs[c] = c; o_used.add(c); s_used.add(c)

    # TIER 2: regra *XX (Oracle '*04' ↔ Sisplan '004')
    for o in o_set - o_used:
        if re.fullmatch(r'\*\d{2}', o):
            cand = '0' + o[1:]
            if cand in s_set - s_used:
                pairs[o] = cand; o_used.add(o); s_used.add(cand)

    # TIER 3: exclusão 1×1
    o_left, s_left = sorted(o_set - o_used), sorted(s_set - s_used)
    if len(o_left) == 1 and len(s_left) == 1:
        pairs[o_left[0]] = s_left[0]

    ora_to_sis[ref] = pairs

# ---------- 4) Lê MOA_VW_VITRINE como fonte de URLs ----------
# URL canônica descoberta 17/05: https://photo.anselmi.ind.br/Fotos/{name}.jpg
# (sem path /cache/ e sem sufixo _1024 — o CDN não tem versão escalada)
# Cor em minúscula no filename: "11739_C25.jpg" → URL com "c25"
PHOTO_BASE = 'https://photo.anselmi.ind.br/Fotos/'

def make_url(filename):
    """11739_C25.jpg → https://photo.anselmi.ind.br/Fotos/11739_c25.jpg"""
    m = re.match(r'^(.+)\.(jpg|jpeg|png)$', filename, re.I)
    if not m: return None
    name, ext = m.groups()
    # Mantém prefixo numérico em maiúsculo, mas força cor (após último _) minúscula
    parts = name.rsplit('_', 1)
    if len(parts) == 2:
        ref_part, cor_part = parts
        name = f'{ref_part}_{cor_part.lower()}'
    else:
        name = name.lower()
    return f'{PHOTO_BASE}{name}.{ext.lower()}'

# Extrai código da cor: "*01 - COR UM" → "*01"
def cor_code(cor_raw):
    if ' - ' in cor_raw:
        return cor_raw.split(' - ', 1)[0].strip()
    return cor_raw.strip()

mv = DATA / 'oracle/moa_vw_vitrine.json'
if not mv.exists():
    sys.exit(f'❌ Arquivo crítico ausente: {mv}')

fotos = []
with open(mv) as f:
    for r in json.load(f).get('rows', []):
        ref = str(r.get('cd_item', '')).strip().zfill(6)
        cor = cor_code(str(r.get('cor', '')))
        filename = str(r.get('url', '')).strip()
        url = make_url(filename)
        if ref and cor and url:
            fotos.append((ref, cor, url))

print(f'Fotos em MOA_VW_VITRINE: {len(fotos):,}')

# ---------- 5) Aplica algoritmo de match (V3: permissivo + tier 4) ----------
banco = collections.defaultdict(lambda: collections.defaultdict(list))
pendencias = []
stats = collections.Counter()

def _norm_cor(c: str) -> str:
    """Normaliza cor: '*04' → '004', 'C25' fica 'C25', '4' → '004'."""
    s = c.strip()
    if re.fullmatch(r'\*\d{2}', s):
        return '0' + s[1:]
    if re.fullmatch(r'\d{1,2}', s):
        return s.zfill(3)
    return s

for ref, cor_file, url in fotos:
    s_set = sisplan.get(ref, set())
    cor_norm = _norm_cor(cor_file)

    # TIER 1: match exato com Sisplan
    if cor_file in s_set:
        banco[ref][cor_file].append(url)
        stats['match_sisplan_direto'] += 1
        continue

    # TIER 2: match normalizado (*04→004, etc) com Sisplan
    if cor_norm in s_set:
        banco[ref][cor_norm].append(url)
        stats['match_normalizado'] += 1
        continue

    # TIER 3: match via ora_to_sis (mapeamento construído acima)
    if cor_file in ora_to_sis.get(ref, {}):
        cs = ora_to_sis[ref][cor_file]
        banco[ref][cs].append(url)
        stats['match_via_oracle'] += 1
        continue

    # TIER 4 (NOVO): ref tem Sisplan mas cor não bate — registra com cor_file
    # original (sem normalizar). Frontend usa fallback "qualquer cor da ref"
    # mas a foto vira disponível pra buscas alternativas.
    if s_set:
        banco[ref][cor_file].append(url)
        stats['match_cor_indireta'] += 1
        continue

    # TIER 5 (NOVO): ref não está no Sisplan mas existe na Oracle (giro).
    # Aceita mesmo assim — produto pode estar ativo mesmo sem cadastro completo.
    if oracle.get(ref):
        banco[ref][cor_norm].append(url)
        stats['match_so_oracle'] += 1
        continue

    # TIER 6 (NOVO): ref não está em nenhum dos catálogos. Aceita ainda assim
    # porque a foto existe e PODE bater com algum SKU vendido. Frontend
    # decide se mostra ou não.
    banco[ref][cor_norm].append(url)
    stats['match_orfa'] += 1

# ---------- 6) Dedupe URLs ----------
for ref in banco:
    for c in banco[ref]:
        banco[ref][c] = list(dict.fromkeys(banco[ref][c]))

# ---------- 7) Salva outputs ----------
from datetime import datetime, timezone
meta = {
    '_meta': {
        'fonte': 'moa_vw_vitrine (Sisplan via Oracle, sincronizado do anselmi-pcp)',
        'gerado_em': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'algoritmo': 'cor_arquivo (MOA_VW_VITRINE) → color_sisplan via JOIN — V3 permissivo (TIER 1-6: direto, normalizado, oracle, indireto, so-oracle, orfa)',
        'estatisticas': dict(stats),
        'fotos_processadas': sum(stats.values()),
        'refs_no_banco': len(banco),
        'pares_ref_color_sisplan': sum(len(c) for c in banco.values()),
    },
    'fotos': {ref: {c: urls for c, urls in cores.items()} for ref, cores in banco.items()},
}

out = DATA / 'banco_fotos.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, separators=(',', ':'))
print(f'✓ {out} ({out.stat().st_size // 1024} KB)')

pend = DATA / 'banco_fotos_pendencias.csv'
with open(pend, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['ref', 'cor_arquivo', 'url', 'motivo'])
    w.writerows(pendencias)
print(f'✓ {pend} ({len(pendencias):,} pendências)')

# ---------- 8) Gera ref_index_sisplan.json — usado pelo vm-loader pra
#                popular REF_INDEX com refs reais (não só mock PECAS).
#                Permite que renderEstoqueCD / renderEstoqueLojas mostrem
#                TODAS as 1.6k refs Sisplan, não só as ~100 do mock.
ref_index = {}
# Lê tipo/descrição direto de vw_prod_info_roi.json (mais limpo que MOA)
sp_path = DATA / 'sisplan/vw_prod_info_roi.json'
if sp_path.exists():
    with open(sp_path) as f:
        for r in json.load(f).get('rows', []):
            ref = str(r.get('rootproductid', '')).strip()
            if not ref or ref in ref_index: continue
            desc = (r.get('description') or '').strip()
            tipo_raw = (r.get('classification1') or '').strip()
            # tipo: "BLUSAS" -> "Blusa", "CAPAS" -> "Capa", etc.
            tipo = tipo_raw.rstrip('S').title() if tipo_raw else 'Peça'
            cor_principal = str(r.get('color', '')).strip()
            ref_index[ref] = {
                'tipo': tipo,
                'descricao': desc,
                'corPrincipal': cor_principal,
            }
# Bonus: enriquece tipo via MOA_VW_VITRINE (mais consistente) se vw_prod não tinha.
# IMPORTANTE: só enriquece refs que JÁ estão no Sisplan vivo — não adiciona refs antigas
# (caso contrário o JSON cresceria pra 18k+ refs com lixo histórico).
if mv.exists():
    with open(mv) as f:
        for r in json.load(f).get('rows', []):
            ref = str(r.get('cd_item', '')).strip().lstrip('0') or '0'
            if not ref or ref not in ref_index: continue
            # já tem do Sisplan — só completa descricao se faltar
            if not ref_index[ref].get('descricao'):
                ref_index[ref]['descricao'] = (r.get('descricao') or '').strip()

idx_out = DATA / 'ref_index_sisplan.json'
with open(idx_out, 'w', encoding='utf-8') as f:
    json.dump({
        '_meta': {
            'fonte': 'vw_prod_info_roi (Sisplan) + moa_vw_vitrine (Oracle)',
            'gerado_em': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'total_refs': len(ref_index),
        },
        'refs': ref_index,
    }, f, ensure_ascii=False, separators=(',', ':'))
print(f'✓ {idx_out} ({idx_out.stat().st_size // 1024} KB · {len(ref_index)} refs)')

print('\n=== ESTATÍSTICAS ===')
total = sum(stats.values())
for k, v in stats.most_common():
    print(f'  {k:30s} {v:>6,}  ({100*v/total:.1f}%)')
matches = sum(v for k, v in stats.items() if 'match' in k)
print(f'\nCobertura: {matches:,}/{total:,} = {100*matches/total:.1f}%')
print(f'Refs no banco: {len(banco):,}')
