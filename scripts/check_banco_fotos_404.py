#!/usr/bin/env python3
"""
check_banco_fotos_404.py
========================
Resolve o TODO documentado no CLAUDE.md:

  "Script de limpeza do banco_fotos.json: rodar HEAD em cada URL, marcar 404,
   regenerar só com URLs válidas"

Lê data/banco_fotos.json, faz HEAD HTTPS em cada URL (~42k) em paralelo, e:
  1. Escreve data/banco_fotos_404.csv  — refs/cores/URLs que retornaram 4xx/5xx
  2. Reescreve data/banco_fotos.json removendo essas URLs (mantém entries que
     ainda têm pelo menos 1 URL válida; remove ref completamente se zerou)
  3. Imprime resumo: total checked / OK / 404 / outros / refs zeradas

Uso:
    python3 scripts/check_banco_fotos_404.py [--workers 32] [--dry-run]

Dependências: só stdlib (urllib + concurrent.futures). Sem requirements.txt.

Tempo esperado: ~5-10 min com 32 workers (depende latência photo.anselmi.ind.br).
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BANCO_PATH = Path(__file__).resolve().parent.parent / "data" / "banco_fotos.json"
CSV_404_PATH = BANCO_PATH.parent / "banco_fotos_404.csv"
TIMEOUT = 15
UA = "Mozilla/5.0 (banco_fotos_check; +github.com/patricia920/anselmi-roi)"


def check_url(url: str, timeout: int = TIMEOUT) -> tuple[str, int | str]:
    """Retorna (url, status) onde status é int HTTP ou string de erro."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return url, resp.status
    except urllib.error.HTTPError as e:
        return url, e.code
    except urllib.error.URLError as e:
        return url, f"err:{getattr(e, 'reason', e)}"
    except Exception as e:  # timeout, ssl, etc
        return url, f"err:{type(e).__name__}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=32, help="threads paralelas (default 32)")
    ap.add_argument("--dry-run", action="store_true", help="só relata, não regrava JSON")
    args = ap.parse_args(argv)

    print(f"→ lendo {BANCO_PATH}")
    raw = json.loads(BANCO_PATH.read_text(encoding="utf-8"))
    fotos = raw.get("fotos") or raw  # tolera shape com ou sem _meta
    meta = raw.get("_meta", {})

    # Coleta todas as URLs únicas (algumas refs/cores compartilham URL)
    url_to_locations: dict[str, list[tuple[str, str, int]]] = {}
    for ref, cores in fotos.items():
        for cor, urls in cores.items():
            for idx, url in enumerate(urls):
                url_to_locations.setdefault(url, []).append((ref, cor, idx))

    print(f"→ {len(fotos):,} refs · {sum(len(c) for c in fotos.values()):,} cores · {len(url_to_locations):,} URLs únicas")
    print(f"→ checando com {args.workers} workers...\n")

    t0 = time.time()
    results: dict[str, int | str] = {}
    done = 0
    total = len(url_to_locations)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(check_url, u): u for u in url_to_locations}
        for f in as_completed(futures):
            url, status = f.result()
            results[url] = status
            done += 1
            if done % 500 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  {done:,}/{total:,} · {rate:.1f} req/s · ETA {eta:.0f}s", file=sys.stderr)

    # Classifica
    ok = {u for u, s in results.items() if isinstance(s, int) and s < 400}
    not_found = {u for u, s in results.items() if isinstance(s, int) and 400 <= s < 500}
    other_err = {u: s for u, s in results.items() if u not in ok and u not in not_found}

    print(f"\n=== Resumo ===")
    print(f"  OK (2xx/3xx): {len(ok):,}")
    print(f"  404/4xx:      {len(not_found):,}")
    print(f"  Outros:       {len(other_err):,}")

    # Escreve CSV das 4xx
    with CSV_404_PATH.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["ref", "color", "url", "status"])
        for url in sorted(not_found):
            for ref, cor, _idx in url_to_locations[url]:
                w.writerow([ref, cor, url, results[url]])
    print(f"  CSV 404:      {CSV_404_PATH}")

    if args.dry_run:
        print("\n(dry-run) JSON não regravado.")
        return 0

    # Regrava JSON sem URLs 4xx (5xx/timeout mantém — pode ser transient)
    refs_zeradas = []
    cores_zeradas = 0
    novas_fotos: dict = {}
    for ref, cores in fotos.items():
        novas_cores: dict = {}
        for cor, urls in cores.items():
            urls_validas = [u for u in urls if u not in not_found]
            if urls_validas:
                novas_cores[cor] = urls_validas
            else:
                cores_zeradas += 1
        if novas_cores:
            novas_fotos[ref] = novas_cores
        else:
            refs_zeradas.append(ref)

    # Atualiza meta
    new_meta = dict(meta)
    new_meta["limpeza_404_em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_meta["urls_404_removidas"] = len(not_found)
    new_meta["refs_zeradas"] = len(refs_zeradas)
    new_meta["cores_zeradas"] = cores_zeradas

    out = {"_meta": new_meta, "fotos": novas_fotos}
    BANCO_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n  banco_fotos.json regravado:")
    print(f"    refs antes: {len(fotos):,} → depois: {len(novas_fotos):,} ({len(refs_zeradas)} zeradas)")
    print(f"    cores zeradas: {cores_zeradas:,}")
    print(f"    URLs removidas: {len(not_found):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
