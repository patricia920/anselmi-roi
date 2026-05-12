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

  // Normaliza ref pro formato canônico do banco: 6 dígitos zero-padded.
  // Sisplan retorna refs com 3-5 dígitos ("414", "11471"), mas banco usa 6 ("000414",
  // "011471"). Sem padding, lookup falha pra 840+ refs.
  function _padRef(ref) {
    if (ref == null) return '';
    const s = String(ref);
    return s.length < 6 ? s.padStart(6, '0') : s;
  }

  function getFotosByRefColor(ref, color) {
    if (!banco) return [];
    const cores = banco[ref] || banco[_padRef(ref)];
    if (!cores) return [];
    return cores[color] || [];
  }

  function getFotos(productid) {
    const d = decompose(productid);
    if (!d) return [];
    return getFotosByRefColor(d.ref, d.color);
  }

  // Pega qualquer foto da mesma ref (qualquer cor disponível).
  // Útil como fallback quando a cor exata não tem foto cadastrada —
  // melhor mostrar a peça em outra cor do que SVG vazio (mesmo molde,
  // só varia cor; usuário ainda reconhece o modelo).
  function getFotoAnyColor(ref) {
    if (!banco) return null;
    const cores = banco[ref] || banco[_padRef(ref)];
    if (!cores) return null;
    const keys = Object.keys(cores);
    for (const k of keys) {
      if (cores[k].length > 0) return cores[k][0];
    }
    return null;
  }

  function getFoto(productid) {
    // 1) tenta foto da cor exata (productid completo: ref+cor+size, ≥9 chars)
    const fotos = getFotos(productid);
    if (fotos.length > 0) return fotos[0];
    // 2) fallback: qualquer foto da mesma ref (peça em outra cor)
    const d = decompose(productid);
    if (d) {
      const anyColor = getFotoAnyColor(d.ref);
      if (anyColor) return anyColor;
    }
    // 3) productid pode ser uma REF pura (sem cor/size) — aceita short SKU
    //    Ex: getFoto('28871') deve retornar alguma foto da ref 28871.
    if (productid) {
      const anyColor = getFotoAnyColor(String(productid));
      if (anyColor) return anyColor;
    }
    return null;
  }

  global.FotoResolver = {
    load,
    getFoto,
    getFotos,
    getFotosByRefColor,
    getFotoAnyColor,
    decompose,
  };
})(typeof window !== 'undefined' ? window : globalThis);
