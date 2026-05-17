"""
validate_banco_fotos.py
========================
Valida cada URL do banco_fotos.json fazendo HEAD request no photo.anselmi.ind.br.

Outputs:
  data/banco_fotos.json              ← regenerado só com URLs 200 OK (in-place)
  data/banco_fotos_invalidas.csv     ← lista de URLs que retornaram 404/erro
  data/banco_fotos_validacao.json    ← stats (total, ok, 404, errors, refs perdidas)

Faz HEAD com 32 threads paralelas (não derruba o Zenphoto, valida ~3-5k URLs/min).
"""
import json, csv, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
DATA = REPO / 'data'

THREADS = 32
TIMEOUT = 10

def head(url):
    """Retorna (status, error) — status 0 se exception."""
    req = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)[:80]

def main():
    src = DATA / 'banco_fotos.json'
    if not src.exists():
        sys.exit(f'❌ Arquivo não encontrado: {src}')
    banco = json.loads(src.read_text())
    fotos = banco.get('fotos', banco)

    # Coleta tarefas únicas (url, ref, cor)
    tasks = []
    for ref, cores in fotos.items():
        for cor, urls in cores.items():
            for url in urls:
                tasks.append((url, ref, cor))
    total = len(tasks)
    print(f'Validando {total:,} URLs com {THREADS} threads (timeout {TIMEOUT}s)…')

    results = []  # [(url, ref, cor, status, error)]
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futs = {pool.submit(head, t[0]): t for t in tasks}
        for fut in as_completed(futs):
            url, ref, cor = futs[fut]
            status, err = fut.result()
            results.append((url, ref, cor, status, err))
            done += 1
            if done % 200 == 0:
                elapsed = time.time() - t0
                eta = (elapsed/done) * (total - done)
                print(f'  {done:>5,}/{total:,}  · {elapsed:.0f}s elapsed · ~{eta:.0f}s restante')

    # Stats
    by_status = {}
    for _,_,_,s,_ in results:
        by_status[s] = by_status.get(s, 0) + 1

    print(f'\n=== Resultado ===')
    for s in sorted(by_status):
        label = 'OK' if s == 200 else ('Network error' if s == 0 else f'HTTP {s}')
        print(f'  {label:>15s}: {by_status[s]:,}')

    # Regenera banco SÓ com URLs 200
    valid_urls = {(r, c, u) for u, r, c, s, _ in results if s == 200}
    new_fotos = {}
    refs_perdidas = []
    for ref, cores in fotos.items():
        new_cores = {}
        for cor, urls in cores.items():
            kept = [u for u in urls if (ref, cor, u) in valid_urls]
            if kept:
                new_cores[cor] = kept
        if new_cores:
            new_fotos[ref] = new_cores
        else:
            # ref perdeu TODAS as cores
            refs_perdidas.append(ref)

    pares_antes = sum(len(c) for c in fotos.values())
    pares_depois = sum(len(c) for c in new_fotos.values())
    urls_antes = sum(len(u) for c in fotos.values() for u in c.values())
    urls_depois = sum(len(u) for c in new_fotos.values() for u in c.values())

    # Salva banco limpo (sobrescreve)
    meta = banco.get('_meta', {})
    meta['validado_em'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    meta['validacao'] = {
        'urls_antes': urls_antes,
        'urls_depois': urls_depois,
        'urls_removidas': urls_antes - urls_depois,
        'refs_perdidas': len(refs_perdidas),
        'pares_antes': pares_antes,
        'pares_depois': pares_depois,
    }
    new_banco = {'_meta': meta, 'fotos': new_fotos}
    src.write_text(json.dumps(new_banco, ensure_ascii=False, separators=(',', ':')))
    print(f'\n✓ banco_fotos.json regenerado:')
    print(f'  Refs: {len(fotos):,} → {len(new_fotos):,} ({len(refs_perdidas)} refs perdidas)')
    print(f'  Pares: {pares_antes:,} → {pares_depois:,}')
    print(f'  URLs: {urls_antes:,} → {urls_depois:,} ({urls_antes-urls_depois:,} removidas)')

    # CSV de inválidas
    invalid = [(u, r, c, s, e) for u, r, c, s, e in results if s != 200]
    inv_path = DATA / 'banco_fotos_invalidas.csv'
    with open(inv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['url', 'ref', 'cor', 'status', 'error'])
        w.writerows(invalid)
    print(f'\n✓ {inv_path} ({len(invalid):,} URLs inválidas)')

    # JSON com stats
    stats_path = DATA / 'banco_fotos_validacao.json'
    stats_path.write_text(json.dumps({
        '_meta': meta['validacao'],
        'validado_em': meta['validado_em'],
        'duracao_s': round(time.time() - t0, 1),
        'por_status': by_status,
        'refs_perdidas': refs_perdidas[:100],  # primeiras 100 pra debug
        'refs_perdidas_total': len(refs_perdidas),
    }, ensure_ascii=False, indent=2))
    print(f'✓ {stats_path}')
    print(f'\nDuração: {time.time()-t0:.1f}s')

if __name__ == '__main__':
    main()
