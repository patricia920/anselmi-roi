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
    loadPromise = Promise.all([
      // Carrega banco_fotos
      fetch(path)
        .then(r => { if (!r.ok) throw new Error('banco_fotos.json HTTP ' + r.status); return r.json(); })
        .then(payload => {
          banco = payload.fotos || payload;
          if (typeof console !== 'undefined') {
            const refs = Object.keys(banco).length;
            let pares = 0, urls = 0;
            for (const r in banco) {
              for (const c in banco[r]) { pares++; urls += banco[r][c].length; }
            }
            console.log(`[FotoResolver] banco carregado: ${refs} refs, ${pares} pares (ref,color), ${urls} URLs`);
          }
          return banco;
        })
        .catch(err => {
          if (typeof console !== 'undefined') console.warn('[FotoResolver] banco falhou:', err.message);
          banco = {};
          return banco;
        }),
      // Carrega cores_plm em paralelo (best-effort — sem cores, fallback "any color")
      loadCoresPlm(),
    ]).then(() => banco);
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

  // Normaliza cor Oracle/Sisplan pro formato do banco:
  //   '*10' (Oracle) → '010' (Sisplan/banco)
  //   '10' → '010' (zero-pad)
  //   'C25' / 'A98' já em formato OK → mantém
  function _normCor(c) {
    if (c == null) return '';
    const s = String(c).trim();
    if (/^\*\d{2}$/.test(s)) return '0' + s.slice(1);   // *10 → 010
    if (/^\d{1,2}$/.test(s)) return s.padStart(3, '0'); // 10 → 010
    return s;
  }

  function getFotosByRefColor(ref, color) {
    if (!banco) return [];
    const cores = banco[ref] || banco[_padRef(ref)];
    if (!cores) return [];
    const c = _normCor(color);
    return cores[c] || cores[color] || cores[String(color).toUpperCase()] || [];
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

  // === Cores PLM (carregadas opcionalmente pra similaridade colorimétrica) ===
  let coresPlm = null;       // {code: {hex, name}}
  let codeToHex = null;       // {sisplanCode: hexString} — index achatado pra lookup rápido

  function _buildColorIndex(plm) {
    const idx = {};
    for (const k in plm) {
      const entry = plm[k];
      if (!entry || !entry.hex) continue;
      const hex = entry.hex.toUpperCase();
      // Indexa pela chave principal
      idx[k] = hex;
      // E por cada parte do `code` (formato "C25 | 1601" ou "*10 | 2001")
      const code = entry.code || '';
      for (const part of code.split('|')) {
        const t = part.trim();
        if (t && !(t in idx)) idx[t] = hex;
      }
    }
    return idx;
  }

  function loadCoresPlm(path) {
    const p = path || 'data/cores_plm.json';
    return fetch(p)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        coresPlm = d || {};
        codeToHex = _buildColorIndex(coresPlm);
        return coresPlm;
      })
      .catch(() => { coresPlm = {}; codeToHex = {}; return {}; });
  }

  // Distância RGB euclidiana entre 2 hex strings (#RRGGBB ou RRGGBB)
  function _hexDistance(h1, h2) {
    if (!h1 || !h2) return Infinity;
    const a = h1.replace('#','');
    const b = h2.replace('#','');
    if (a.length !== 6 || b.length !== 6) return Infinity;
    const r1 = parseInt(a.slice(0,2),16), g1 = parseInt(a.slice(2,4),16), b1 = parseInt(a.slice(4,6),16);
    const r2 = parseInt(b.slice(0,2),16), g2 = parseInt(b.slice(2,4),16), b2 = parseInt(b.slice(4,6),16);
    return Math.sqrt((r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2);
  }

  // Acha a cor mais SIMILAR (em RGB) dentre as cores disponíveis pra ref
  function getFotoSimilarColor(ref, targetColor) {
    if (!banco || !codeToHex) return null;
    const cores = banco[ref] || banco[_padRef(ref)];
    if (!cores) return null;
    const targetHex = codeToHex[targetColor] || codeToHex[_normCor(targetColor)];
    if (!targetHex) return null;
    // Ranqueia cores disponíveis pela distância
    let best = null;
    let bestDist = Infinity;
    for (const c in cores) {
      if (!cores[c] || !cores[c].length) continue;
      const hex = codeToHex[c];
      if (!hex) continue;
      const d = _hexDistance(targetHex, hex);
      if (d < bestDist) {
        bestDist = d;
        best = { url: cores[c][0], color: c, hex, distance: d };
      }
    }
    return best;
  }

  function getFoto(productid, opts) {
    opts = opts || {};
    // 1) cor exata
    const fotos = getFotos(productid);
    if (fotos.length > 0) return fotos[0];
    const d = decompose(productid);
    // 2) cor SIMILAR (via hex distance) — preferida sobre "any color"
    if (d) {
      const similar = getFotoSimilarColor(d.ref, d.color);
      if (similar) {
        if (opts.withMeta) {
          return { url: similar.url, color: similar.color, similar: true, distance: similar.distance };
        }
        return similar.url;
      }
      // 3) fallback final: qualquer cor (sem similaridade)
      const anyColor = getFotoAnyColor(d.ref);
      if (anyColor) {
        if (opts.withMeta) return { url: anyColor, similar: true, distance: null };
        return anyColor;
      }
    }
    // 4) productid pode ser ref pura
    if (productid) {
      const anyColor = getFotoAnyColor(String(productid));
      if (anyColor) {
        if (opts.withMeta) return { url: anyColor, similar: true, distance: null };
        return anyColor;
      }
    }
    return null;
  }

  global.FotoResolver = {
    load,
    loadCoresPlm,
    getFoto,
    getFotos,
    getFotosByRefColor,
    getFotoAnyColor,
    getFotoSimilarColor,
    decompose,
  };
})(typeof window !== 'undefined' ? window : globalThis);
