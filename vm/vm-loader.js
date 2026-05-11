/**
 * vm/vm-loader.js
 * ---------------
 * Carrega os globals que vm/index.html espera ANTES da página rodar:
 *
 *   window.FOTOS_INDEX   { ref → url da foto principal }   ← photo.anselmi.ind.br
 *   window.FOTOS_CORES   { ref → [{codigo,hex,url}, ...] } ← photo.anselmi + PLM
 *   window.COR_PLM       { codigo → {hex, nome, ...} }     ← cores_plm.json (sync pcp)
 *
 * FONTE DE FOTOS: photo.anselmi.ind.br via lib/foto-resolver.js + data/banco_fotos.json
 * (mesmo padrão das outras páginas do ROI — reabastecimento, excesso, transferências).
 *
 * As cores PLM (hex/nome) continuam vindo do anselmi-pcp/data/cores_plm.json,
 * sincronizado pelo workflow sync_from_pcp.yml. Photo NÃO depende disso.
 */

(function () {
  'use strict';

  const T0 = performance.now();
  const TASKS = [];

  // 1) carregar foto-resolver.js dinamicamente (mesmo que index.html não tenha o <script>)
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.async = false;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('script ' + src));
      document.head.appendChild(s);
    });
  }

  async function loadFotoResolver() {
    if (window.FotoResolver) return window.FotoResolver;
    try {
      await loadScript('../lib/foto-resolver.js');
    } catch (e) {
      console.warn('[vm-loader] foto-resolver.js não carregou:', e.message);
      return null;
    }
    return window.FotoResolver || null;
  }

  // 2) JSON loader genérico
  async function loadJSON(path) {
    try {
      const r = await fetch(path, { credentials: 'omit', cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } catch (e) {
      console.warn('[vm-loader] falhou', path, '·', e.message);
      return null;
    }
  }

  // 3) deriva FOTOS_INDEX (ref → url principal) a partir do banco do FotoResolver
  function buildFotosIndex(banco) {
    const idx = {};
    if (!banco) return idx;
    for (const ref in banco) {
      const cores = banco[ref];
      if (!cores) continue;
      // pega a 1ª cor que tem URL (qualquer cor da mesma ref)
      for (const cor in cores) {
        const urls = cores[cor];
        if (Array.isArray(urls) && urls.length > 0) {
          idx[ref] = urls[0];
          break;
        }
      }
    }
    return idx;
  }

  // 4) deriva FOTOS_CORES (ref → [{codigo, hex, url}]) combinando banco + COR_PLM
  function buildFotosCores(banco, corPlm) {
    const out = {};
    if (!banco) return out;
    for (const ref in banco) {
      const cores = banco[ref];
      if (!cores) continue;
      const arr = [];
      for (const codigo in cores) {
        const urls = cores[codigo];
        if (!Array.isArray(urls) || urls.length === 0) continue;
        const meta = (corPlm && corPlm[codigo]) || (corPlm && corPlm[codigo.toUpperCase()]) || null;
        arr.push({
          codigo,
          hex: meta && meta.hex ? '#' + String(meta.hex).replace(/^#/, '') : null,
          nome: meta ? (meta.nome || meta.descricao || null) : null,
          url: urls[0],
          fotos: urls,
        });
      }
      if (arr.length) out[ref] = arr;
    }
    return out;
  }

  // 5) status pra UI (rodapé #est-integ-msg)
  function paintStatus({ corPlm, fotoCount, vedActive }) {
    const el = document.getElementById('est-integ-msg');
    if (!el) return;
    const partes = [];
    partes.push(vedActive
      ? `<b>Sisplan:</b> ativa (${Object.keys(window.VAR_LOJAS).length} lojas)`
      : `<b>Sisplan:</b> ved_varejo.js não carregou — modo mock`);
    partes.push(`<b>Fotos:</b> ${fotoCount.toLocaleString('pt-BR')} refs (photo.anselmi.ind.br)`);
    if (corPlm) partes.push(`<b>PLM cores:</b> ${Object.keys(corPlm).length} códigos`);
    el.innerHTML = partes.join(' · ');
  }

  // 6) boot
  async function boot() {
    // dispara as cargas em paralelo
    const fotoResolverP = loadFotoResolver();
    const corPlmP = loadJSON('../data/cores_plm.json');

    const [FotoResolver, corPlm] = await Promise.all([fotoResolverP, corPlmP]);

    // FotoResolver.load() puxa data/banco_fotos.json (photo.anselmi.ind.br)
    let banco = null;
    if (FotoResolver && typeof FotoResolver.load === 'function') {
      try {
        await FotoResolver.load('../data/banco_fotos.json');
        // O foto-resolver guarda o banco internamente; recuperamos lendo do escopo dele
        // via uma sondagem: getFoto('______') retorna null mas o banco fica carregado.
        // Como ele expõe getFotosByRefColor(ref, color), precisamos acessar o banco direto.
        // Hack mínimo: re-fetch do JSON em paralelo (cache do browser dá HIT).
      } catch (e) {
        console.warn('[vm-loader] FotoResolver.load falhou:', e.message);
      }
    }
    const bancoRaw = await loadJSON('../data/banco_fotos.json');
    banco = bancoRaw ? (bancoRaw.fotos || bancoRaw) : null;

    // monta os globals esperados pela página
    if (corPlm) {
      window.COR_PLM = corPlm;
      console.info('[vm-loader] COR_PLM ·', Object.keys(corPlm).length, 'cores');
    }

    const fotosIndex = buildFotosIndex(banco);
    if (Object.keys(fotosIndex).length) {
      window.FOTOS_INDEX = fotosIndex;
      console.info('[vm-loader] FOTOS_INDEX ·', Object.keys(fotosIndex).length, 'refs (photo.anselmi)');
    }

    const fotosCores = buildFotosCores(banco, corPlm);
    if (Object.keys(fotosCores).length) {
      window.FOTOS_CORES = fotosCores;
      console.info('[vm-loader] FOTOS_CORES ·', Object.keys(fotosCores).length, 'refs');
    }

    // marca pronto + dispara evento (a página pode escutar pra re-render se quiser)
    window.__vmLoaderReady = true;
    document.dispatchEvent(new CustomEvent('vm-loader:ready', {
      detail: {
        elapsedMs: Math.round(performance.now() - T0),
        corPlm: !!corPlm,
        fotos: Object.keys(fotosIndex).length,
        fotosCores: Object.keys(fotosCores).length,
        vedActive: typeof window.VAR_LOJAS === 'object' && !!window.VAR_LOJAS,
      },
    }));

    paintStatus({
      corPlm,
      fotoCount: Object.keys(fotosIndex).length,
      vedActive: typeof window.VAR_LOJAS === 'object' && !!window.VAR_LOJAS,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
