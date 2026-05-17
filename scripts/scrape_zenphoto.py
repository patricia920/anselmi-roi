"""
scrape_zenphoto.py
====================
Scrape do álbum Fotos do Zenphoto Anselmi (photo.anselmi.ind.br/Fotos/) pra
descobrir TODAS as fotos que existem no servidor, não só o subset mapeado pelo
MOA_VW_VITRINE.

Estratégia:
  1. Itera páginas 1..N do álbum Fotos
  2. Extrai filenames /Fotos/REF_COR.jpg de cada página
  3. Mescla com data/banco_fotos.json (mantém URLs Parte A já validadas)
  4. Pra cada filename novo descoberto: adiciona como ref_zero_pad → cor → URL

Output:
  data/banco_fotos.json (mesclado, in-place)
  data/banco_fotos_zenphoto_descobertas.csv (refs/cores novas que vieram do scrape)
"""
import json, csv, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
DATA = REPO / 'data'

BASE = 'https://photo.anselmi.ind.br/Fotos/'
THUMB_BASE = 'https://photo.anselmi.ind.br/cache/Fotos/'
THREADS = 16
TIMEOUT = 15

# Regex pra capturar /Fotos/REF_COR.jpg (não pega thumbs /cache/ nem _1.jpg variants)
RE_PHOTO = re.compile(r'/Fotos/(\d+)_([A-Z0-9]+)\.(?:jpg|jpeg|png|webp)', re.I)
RE_TOTAL = re.compile(r'of\s+([\d,]+)\s+(?:images|imagens)')

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 anselmi-roi-scraper'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception as e:
        return None

def scrape_page(n):
    """Retorna set de tuplas (ref, cor) extraídas da página."""
    url = f'{BASE}page/{n}/' if n > 1 else BASE
    html = fetch(url)
    if not html: return None
    pairs = set()
    for m in RE_PHOTO.finditer(html):
        ref, cor = m.group(1), m.group(2).upper()
        pairs.add((ref, cor))
    return pairs

def main():
    # Descobre total de páginas via page 1
    print('Buscando página 1…')
    html = fetch(BASE)
    if not html:
        sys.exit('❌ Falhou fetch página 1')

    # Acha o page/N maior referenciado no paginador
    pages_found = [int(m.group(1)) for m in re.finditer(r'page/(\d+)/?', html)]
    total_pages = max(pages_found) if pages_found else 1
    print(f'Total de páginas: {total_pages}')

    # Scrape em paralelo
    pairs_global = set()
    page_pairs = scrape_page(1)
    if page_pairs: pairs_global.update(page_pairs)

    t0 = time.time()
    failed = []
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = {pool.submit(scrape_page, n): n for n in range(2, total_pages+1)}
        done = 1
        for fut in as_completed(futs):
            n = futs[fut]
            res = fut.result()
            done += 1
            if res is None:
                failed.append(n)
            else:
                pairs_global.update(res)
            if done % 50 == 0:
                elapsed = time.time() - t0
                eta = (elapsed/done) * (total_pages - done)
                print(f'  {done}/{total_pages} páginas · {elapsed:.0f}s · ~{eta:.0f}s restante · {len(pairs_global):,} pares únicos')

    print(f'\n✓ Scrape concluído em {time.time()-t0:.1f}s')
    print(f'  Total pares (ref,cor): {len(pairs_global):,}')
    if failed:
        print(f'  ⚠ {len(failed)} páginas falharam (retry manual): {failed[:10]}')

    # Carrega banco atual
    banco_path = DATA / 'banco_fotos.json'
    banco = json.loads(banco_path.read_text())
    fotos = banco.get('fotos', banco)

    # Mescla: pra cada (ref, cor) do Zenphoto, padda ref pra 6 dig e adiciona se faltar
    novas = []
    for ref, cor in pairs_global:
        ref6 = ref.zfill(6)
        # URL canônica thumbnail
        url = f'{THUMB_BASE}{ref}_{cor}_1024.jpg'
        if ref6 not in fotos:
            fotos[ref6] = {}
        if cor not in fotos[ref6]:
            fotos[ref6][cor] = [url]
            novas.append({'ref': ref6, 'cor': cor, 'url': url})
        elif url not in fotos[ref6][cor]:
            fotos[ref6][cor].append(url)

    print(f'\n  Refs/cores novas adicionadas: {len(novas):,}')
    print(f'  Total refs no banco: {len(fotos):,}')
    print(f'  Total pares: {sum(len(c) for c in fotos.values()):,}')

    # Atualiza meta
    meta = banco.get('_meta', {})
    meta['zenphoto_scrape_em'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    meta['zenphoto_descobertas'] = len(novas)

    new_banco = {'_meta': meta, 'fotos': fotos}
    banco_path.write_text(json.dumps(new_banco, ensure_ascii=False, separators=(',', ':')))
    print(f'\n✓ {banco_path}')

    # CSV das novas
    csv_path = DATA / 'banco_fotos_zenphoto_descobertas.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['ref', 'cor', 'url'])
        w.writerows([(n['ref'], n['cor'], n['url']) for n in novas])
    print(f'✓ {csv_path} ({len(novas):,} descobertas)')

if __name__ == '__main__':
    main()
