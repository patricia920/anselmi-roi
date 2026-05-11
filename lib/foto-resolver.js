/**
 * foto-resolver.js
 * ----------------
 * Resolver de fotos do dashboard ROI Anselmi.
 *
 * Carrega data/banco_fotos.json (gerado por build_banco_fotos.py — cruzando
 * Sisplan vw_prod_info_roi com Oracle vw_giro_estoque/venda/costura) e expõe:
 *
 *   FotoResolver.load()                       → Promise (carrega o banco 1×)
 *   FotoResolver.getFoto(productid)           → URL principal ou null
 *   FotoResolver.getFotos(productid)          → array de URLs (todas as fotos)
 *   FotoResolver.getFotosByRefColor(ref,col)  → array de URLs
 *   FotoResolver.decompose(productid)         → {ref, color, size}
 *
 * Decomposição do productid Sisplan:
 *   011739C25     → ref=011739 color=C25 size=''
 *   011861010M    → ref=011861 color=010 size='M'
 *   010974D62PP   → ref=010974 color=D62 size='PP'
 *   024845324M    → ref=024845 color=324 size='M'
 *
 * Padrão: chars 0-5 = ref (6 dig), chars 6-8 = color (3 chars), resto = size.
 *
 * Uso típico (não-bloqueante):
 *   await FotoResolver.load();
 *   const url = FotoResolver.getFoto('011739C25');  // → URL ou null
 *
 * Compat: substitui o const FOTOS = {...} embarcado nos HTMLs.
 * Se o banco falhar ao carregar, FotoResolver.getFoto retorna null e o
 * fallback SVG por categoria continua funcionando.
 */
(function (global) {
  'use strict';

  let banco = null;       // {ref: {color: [urls...]}}
  let loadPromise = null;

  function decompose(pid) {
    if (!pid || typeof pid !== 'string' || pid.length < 9) return null;
    return {
      ref:   pid.slice(0, 6),
      color: pid.slice(6, 9),
      size:  pid.slice(9),
    };
  }

  function load(jsonPath) {
    if (banco) return Promise.resolve(banco);
    if (loadPromise) return loadPromise;
    const path = jsonPath || 'data/banco_fotos.json';
    loadPromise = fetch(path)
      .then(r => {
        if (!r.ok) throw new Error('banco_fotos.json HTTP ' + r.status);
        return r.json();
      })
      .then(payload => {
        banco = payload.fotos || payload;  // tolera os 2 formatos
        if (typeof console !== 'undefined') {
          const refs = Object.keys(banco).length;
          let pares = 0, urls = 0;
          for (const r in banco) {
            for (const c in banco[r]) {
              pares++; urls += banco[r][c].length;
            }
          }
          console.log(`[FotoResolver] banco carregado: ${refs} refs, ${pares} pares (ref,color), ${urls} URLs`);
        }
        return banco;
      })
      .catch(err => {
        if (typeof console !== 'undefined') console.warn('[FotoResolver] falhou:', err.message);
        banco = {};  // fallback vazio — getFoto retorna null
        return banco;
      });
    return loadPromise;
  }

  function getFotosByRefColor(ref, color) {
    if (!banco) return [];
    const cores = banco[ref];
    if (!cores) return [];
    return cores[color] || [];
  }

  function getFotos(productid) {
    const d = decompose(productid);
    if (!d) return [];
    return getFotosByRefColor(d.ref, d.color);
  }

  function getFoto(productid) {
    const fotos = getFotos(productid);
    return fotos.length > 0 ? fotos[0] : null;
  }

  global.FotoResolver = {
    load,
    getFoto,
    getFotos,
    getFotosByRefColor,
    decompose,
  };
})(typeof window !== 'undefined' ? window : globalThis);
