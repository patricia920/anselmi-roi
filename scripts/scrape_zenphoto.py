"""
scrape_zenphoto.py · v2 com retry + backoff
=============================================
Scrape do álbum Fotos do Zenphoto Anselmi (photo.anselmi.ind.br/Fotos/) pra
descobrir TODAS as fotos que existem no servidor, não só o subset mapeado pelo
MOA_VW_VITRINE.

Estratégia:
  1. Itera páginas 1..N do álbum Fotos
  2. Extrai filenames /Fotos/REF_COR.jpg de cada página
  3. Mescla com data/banco_fotos.json (mantém URLs Parte A já validadas)
  4. Pra cada filename novo descoberto: adiciona como ref_zero_pad → cor → URL

Mudanças v2 (resolve falha de 465/470 páginas em 2026-05-18):
  • THREADS=4 (era 16) — Zenphoto começa a rejeitar acima de ~5 conexões
  • Retry exponencial: 3 tentativas por página com backoff 1s · 3s · 9s
  • Throttle: 200ms entre requests no mesmo thread
  • Detecção de 429/503: pausa global de 30s quando aparece
  • User-Agent mais realista
  • Re-roda automaticamente as páginas que falharam no fim
  • URL canônica: /Fotos/REF_COR.jpg (sem /cache/ e sem _1024 — bate com
    o que está no banco_fotos.json já validado)

Output:
  data/banco_fotos.json (mesclado, in-place)
  data/banco_fotos_zenphoto_descobertas.csv (refs/cores novas que vieram do scrape)
"""
import json, csv, re, sys, time, urllib.request, urllib.error
import random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
DATA = REPO / 'data'

BASE = 'https://photo.anselmi.ind.br/Fotos/'
# URL canônica: sem /cache/ e sem _1024 (mesmo formato do build_banco_fotos_v2.py
# e do que o app espera no banco_fotos.json).
PHOTO_BASE = 'https://photo.anselmi.ind.br/Fotos/'

THREADS = 4               # era 16 — reduzir pra evitar rate limit
TIMEOUT = 20
THROTTLE_MS = 200         # delay mínimo entre requests no mesmo thread
RETRY_MAX = 3             # tentativas por página
RETRY_BACKOFF_BASE = 1.0  # delay base · vira 1s, 3s, 9s (exponencial)
RATE_LIMIT_PAUSE = 30     # pausa global quando aparece 429/503
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) '
    'Version/17.0 Safari/605.1.15'
)

# Regex pra capturar /Fotos/REF_COR.jpg (não pega thumbs /cache/ nem _1.jpg variants)
RE_PHOTO = re.compile(r'/Fotos/(\d+)_([A-Z0-9]+)\.(?:jpg|jpeg|png|webp)', re.I)

# Lock + flag global pra coordenar throttle em caso de rate limit detectado
_rate_limit_lock = threading.Lock()
_rate_limit_until = [0.0]  # mutable container pra usar dentro de threads
_last_request_per_thread = {}  # thread_id → timestamp


def _throttle():
    """Garante delay mínimo entre requests no mesmo thread + respeita pausa global."""
    # Pausa global por rate limit detectado
    with _rate_limit_lock:
        wait = _rate_limit_until[0] - time.time()
    if wait > 0:
        time.sleep(wait)

    # Throttle por thread
    tid = threading.get_ident()
    last = _last_request_per_thread.get(tid, 0)
    elapsed = time.time() - last
    if elapsed < THROTTLE_MS / 1000.0:
        time.sleep(THROTTLE_MS / 1000.0 - elapsed)
    _last_request_per_thread[tid] = time.time()


def _trigger_rate_limit_pause():
    """Quando detecta 429/503, pausa global por RATE_LIMIT_PAUSE segundos."""
    with _rate_limit_lock:
        until = time.time() + RATE_LIMIT_PAUSE
        if until > _rate_limit_until[0]:
            _rate_limit_until[0] = until
    print(f'  ⏸ rate limit detectado · pausando {RATE_LIMIT_PAUSE}s', file=sys.stderr)


def fetch(url, attempt=1):
    """Fetch com retry exponencial. Retorna HTML ou None se todas falharem."""
    _throttle()
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        if e.code in (429, 503):
            _trigger_rate_limit_pause()
        if attempt < RETRY_MAX:
            backoff = RETRY_BACKOFF_BASE * (3 ** (attempt - 1))  # 1, 3, 9
            # Jitter ±20% pra evitar thundering herd
            backoff *= 0.8 + 0.4 * random.random()
            time.sleep(backoff)
            return fetch(url, attempt + 1)
        return None
    except Exception:
        if attempt < RETRY_MAX:
            backoff = RETRY_BACKOFF_BASE * (3 ** (attempt - 1))
            backoff *= 0.8 + 0.4 * random.random()
            time.sleep(backoff)
            return fetch(url, attempt + 1)
        return None


def scrape_page(n):
    """Retorna set de tuplas (ref, cor) extraídas da página."""
    url = f'{BASE}page/{n}/' if n > 1 else BASE
    html = fetch(url)
    if not html:
        return None
    pairs = set()
    for m in RE_PHOTO.finditer(html):
        ref, cor = m.group(1), m.group(2).upper()
        pairs.add((ref, cor))
    return pairs


def scrape_pages(page_list, label='scraping'):
    """Scrape paralela de uma lista de números de página. Retorna (pairs, falhadas)."""
    pairs_acc = set()
    failed_pages = []
    t0 = time.time()
    total = len(page_list)
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = {pool.submit(scrape_page, n): n for n in page_list}
        for fut in as_completed(futs):
            n = futs[fut]
            res = fut.result()
            done += 1
            if res is None:
                failed_pages.append(n)
            else:
                pairs_acc.update(res)
            if done % 50 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f'  [{label}] {done}/{total} · {elapsed:.0f}s · ~{eta:.0f}s restante · {len(pairs_acc):,} pares · {len(failed_pages)} falhas')
    return pairs_acc, failed_pages


def main():
    # Descobre total de páginas via page 1
    print('Buscando página 1…')
    html = fetch(BASE)
    if not html:
        sys.exit('❌ Falhou fetch página 1')

    pages_found = [int(m.group(1)) for m in re.finditer(r'page/(\d+)/?', html)]
    total_pages = max(pages_found) if pages_found else 1
    print(f'Total de páginas: {total_pages}')
    print(f'Config: {THREADS} threads · throttle {THROTTLE_MS}ms · retry {RETRY_MAX}× backoff exponencial')
    print()

    # Pares da página 1 (já foi fetched acima)
    pairs_global = set()
    for m in RE_PHOTO.finditer(html):
        pairs_global.add((m.group(1), m.group(2).upper()))

    # Primeira passada · páginas 2..N
    print('— Primeira passada —')
    pairs1, failed1 = scrape_pages(list(range(2, total_pages + 1)), label='pass1')
    pairs_global.update(pairs1)
    print(f'  Pass 1: {len(pairs1):,} pares · {len(failed1)} falhas')

    # Re-tenta as falhadas (rate limit já passou, throttle calmo)
    if failed1:
        print(f'\n— Re-tentando {len(failed1)} páginas falhadas —')
        time.sleep(5)  # cooldown antes de re-tentar
        pairs2, failed2 = scrape_pages(failed1, label='pass2')
        pairs_global.update(pairs2)
        print(f'  Pass 2: recuperadas {len(failed1) - len(failed2)} páginas · {len(failed2)} ainda falhando')
    else:
        failed2 = []

    print(f'\n✓ Scrape concluído')
    print(f'  Total pares (ref,cor) coletados: {len(pairs_global):,}')
    if failed2:
        print(f'  ⚠ {len(failed2)} páginas ainda falham (re-rodar manual depois): {failed2[:20]}')

    # Carrega banco atual
    banco_path = DATA / 'banco_fotos.json'
    banco = json.loads(banco_path.read_text())
    fotos = banco.get('fotos', banco)

    # Mescla: pra cada (ref, cor) do Zenphoto, padda ref pra 6 dig e adiciona se faltar
    novas = []
    for ref, cor in pairs_global:
        ref6 = ref.zfill(6)
        # URL canônica: /Fotos/REF_COR.jpg (mesmo formato do banco já validado)
        # build_banco_fotos_v2.py usa esse formato; check_banco_fotos_404.py testa esse.
        url = f'{PHOTO_BASE}{ref}_{cor.lower()}.jpg'
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
    if failed2:
        meta['zenphoto_paginas_ainda_falham'] = failed2

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
