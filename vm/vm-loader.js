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

  // 2) JSON loader genérico — manda cookie de sessão (same-origin) pra passar
  //    pelo _middleware.js de auth. credentials: 'omit' fazia o middleware
  //    redirecionar pra /login (HTML fallback) em TODAS as requests.
  async function loadJSON(path, attempt = 0) {
    try {
      const url = attempt > 0 ? path + (path.includes('?') ? '&' : '?') + 'cb=' + Date.now() : path;
      const r = await fetch(url, { credentials: 'same-origin', cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const text = await r.text();
      // Detecta HTML fallback: começa com '<' → cache miss servindo /index.html
      if (text.trimStart().startsWith('<')) {
        if (attempt < 2) {
          await new Promise(r => setTimeout(r, 800 + attempt * 600));
          return loadJSON(path, attempt + 1);
        }
        throw new Error('HTML fallback após retries');
      }
      return JSON.parse(text);
    } catch (e) {
      if (attempt === 0 && /JSON|HTML fallback/.test(e.message)) {
        // Tenta de novo (cache miss)
        await new Promise(r => setTimeout(r, 800));
        return loadJSON(path, 1);
      }
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
    const lojaMapP = loadJSON('../data/loja_map.json');

    // LOJA_MAP é independente das fotos — atribui assim que chegar,
    // pra evitar que falha de banco_fotos atrase a montagem do LOJAS Sisplan.
    lojaMapP.then(lojaMapData => {
      if (lojaMapData && lojaMapData.map) {
        window.LOJA_MAP = lojaMapData.map;
        const mapped = Object.values(lojaMapData.map).filter(Boolean).length;
        console.info('[vm-loader] LOJA_MAP ·', mapped, 'lojas com slug/planta');
        // Reconstroi LOJAS com slugs reais + recalcula KPIs do header
        if (typeof window._buildLojasFromVar === 'function') window._buildLojasFromVar();
        if (typeof window.updateHeaderKpis === 'function') window.updateHeaderKpis();
      }
    }).catch(err => console.warn('[vm-loader] LOJA_MAP load falhou:', err.message));

    // GERENTES: carrega data/gerentes.json e mescla com const GERENTES default
    loadJSON('../data/gerentes.json').then(data => {
      if (!data || !data.gerentes) return;
      window.GERENTES_DATA = data.gerentes;
      if (typeof window.GERENTES === 'object' && window.GERENTES) {
        Object.assign(window.GERENTES, data.gerentes);
        const total = Object.keys(data.gerentes).length;
        const named = Object.values(data.gerentes).filter(g => g && g.nome && g.nome !== 'A definir').length;
        console.info('[vm-loader] GERENTES ·', named, 'com nome /', total, 'lojas');
      }
    }).catch(err => console.warn('[vm-loader] GERENTES load falhou:', err.message));

    // REF_INDEX_SISPLAN: carrega data/ref_index_sisplan.json (1.6k refs com tipo/descrição
    // do Sisplan) e MERGE com const REF_INDEX da página. Sem isso, renderEstoqueCD /
    // renderEstoqueLojas pulam ~94% das refs reais porque PECAS mock só cobre ~100.
    loadJSON('../data/ref_index_sisplan.json').then(data => {
      if (!data || !data.refs) return;
      // Aguarda a página declarar REF_INDEX (definido em vm/index.html linha ~3350)
      const tryMerge = () => {
        if (typeof window.REF_INDEX !== 'object' || !window.REF_INDEX) return setTimeout(tryMerge, 300);
        let added = 0, overridden = 0;
        // Sisplan é fonte autoritativa. PROPAGA pras DUAS chaves possíveis (5d e 6d):
        // mock cadastra refs com '28871' (5 dig), Sisplan vem como '028871' (6 dig zero-pad).
        // Sem propagar, lookup de 5d retorna mock errado (Capa/Off Camelo) em vez do real (Básica/001).
        Object.entries(data.refs).forEach(([ref6d, meta]) => {
          const ref5d = ref6d.replace(/^0+/, '') || '0';
          const keys = ref5d === ref6d ? [ref6d] : [ref6d, ref5d];
          keys.forEach(k => {
            if (!window.REF_INDEX[k]) {
              window.REF_INDEX[k] = {
                ref: k,
                tipo: meta.tipo || 'Peça',
                descricao: meta.descricao || '',
                est: 'I-26',
                cores: meta.corPrincipal ? [meta.corPrincipal] : [],
                corPrincipal: meta.corPrincipal || '',
                estoque: 0, vendas30: 0, emVM: 0, lojasComEstoque: 0, cdQty: 0,
                status: 'unknown', sugestao: '', _sisplan: true,
              };
              added++;
            } else {
              const e = window.REF_INDEX[k];
              if (meta.tipo && e.tipo !== meta.tipo) { e.tipo = meta.tipo; overridden++; }
              if (meta.corPrincipal && e.corPrincipal !== meta.corPrincipal) {
                e.corPrincipal = meta.corPrincipal;
                if (!Array.isArray(e.cores) || !e.cores.includes(meta.corPrincipal)) {
                  e.cores = [meta.corPrincipal, ...(e.cores || []).filter(c => c !== meta.corPrincipal)];
                }
              }
              if (meta.descricao && !e.descricao) e.descricao = meta.descricao;
            }
          });
        });
        console.info('[vm-loader] REF_INDEX · +' + added + ' refs Sisplan, ' + overridden + ' tipos corrigidos (Sisplan sobrescreve mock)');
        // Re-renderiza views que dependem do REF_INDEX completo
        ['renderEstoqueCD', 'renderEstoqueLojas', 'renderVendasLoja'].forEach(fn => {
          if (typeof window[fn] === 'function') {
            try { window[fn](); } catch (_) {}
          }
        });
        // Recalcula ranking automático com vendas reais (Sisplan) — substitui mock inicial
        if (typeof window.applyRankingForLoja === 'function') {
          const codInicial = (typeof window.currentStore === 'object' && window.currentStore?.cod) || '*';
          try {
            window.applyRankingForLoja(codInicial).catch?.(()=>{});
            console.info('[vm-loader] Ranking recalculado (Sisplan) para', codInicial);
          } catch (_) {}
        }
      };
      tryMerge();
    }).catch(err => console.warn('[vm-loader] REF_INDEX_SISPLAN load falhou:', err.message));

    // PALETA da coleção: carrega data/paleta_colecao.json e enriquece hex com COR_PLM se nome bate
    loadJSON('../data/paleta_colecao.json').then(data => {
      if (!data || !Array.isArray(data.paleta)) return;
      const paleta = data.paleta.slice();
      // Enriquecimento: se window.COR_PLM tem cor com mesmo nome (case-insensitive), usa hex do PLM
      if (window.COR_PLM) {
        const plmByName = {};
        Object.values(window.COR_PLM).forEach(c => {
          if (c && c.name) plmByName[c.name.toLowerCase()] = c.hex;
          if (c && c.nome) plmByName[c.nome.toLowerCase()] = c.hex;
        });
        let enriched = 0;
        paleta.forEach(p => {
          const plmHex = plmByName[(p.nome || '').toLowerCase()];
          if (plmHex && plmHex.replace(/^#/, '') !== (p.hex || '').replace(/^#/, '')) {
            p._hex_mock = p.hex;
            p.hex = '#' + plmHex.replace(/^#/, '');
            enriched++;
          }
        });
        console.info('[vm-loader] PALETA · ', paleta.length, 'cores · ', enriched, 'hex sobrescritos pelo PLM');
      }
      window.PALETA_COLECAO_DATA = { colecao: data.colecao, paleta };
      // Mescla na const PALETA_COLECAO se existir
      if (typeof window.PALETA_COLECAO !== 'undefined' && Array.isArray(window.PALETA_COLECAO)) {
        window.PALETA_COLECAO.length = 0;
        paleta.forEach(p => window.PALETA_COLECAO.push(p));
        if (typeof window.renderCores === 'function') window.renderCores();
        if (typeof window.renderPaletaColecao === 'function') window.renderPaletaColecao();
      }
    }).catch(err => console.warn('[vm-loader] PALETA load falhou:', err.message));

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
