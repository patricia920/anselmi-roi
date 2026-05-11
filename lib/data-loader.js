// ============================================================================
// data-loader.js — helper de carregamento de JSONs do pipeline anselmi-pcp
// ============================================================================
// Padrão usado pelo repo_widget.js da aba Reposição em desktop.html:
//   data/volution/{nome}-report.json.gz  →  DecompressionStream  →  JSON.parse
//
// Cada HTML do MVP usa loadReport(name, {fallback}) pra carregar seu JSON.
// Se o fetch falhar (ex: arquivo ainda não gerado), cai no fallback (RAW embutido).
// Em produção, fallback pode ser removido depois que pipeline estiver estável.
// ============================================================================

(function(global){
  'use strict';

  // URL absoluta porque o ROI roda em projeto Cloudflare Pages separado (anselmi-roi)
  // mas os JSONs são gerados/servidos pelo projeto anselmi-producao (anselmi-pcp repo).
  // Requer CORS habilitado em /data/volution/ via _headers do anselmi-producao.
  const BASE = 'https://anselmi-producao.pages.dev/data/volution/';

  function decompressGz(buf){
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('DecompressionStream não suportado no navegador');
    }
    const ds = new DecompressionStream('gzip');
    const stream = new Response(buf).body.pipeThrough(ds);
    return new Response(stream).text();
  }

  // Carrega report .json.gz e retorna {ok, data, error, fromFallback, exportedAt}
  async function loadReport(name, options){
    options = options || {};
    const url = (options.basePath || BASE) + name + '-report.json.gz';
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const buf = await r.arrayBuffer();
      const txt = await decompressGz(buf);
      const data = JSON.parse(txt);
      return {
        ok: true,
        data: data,
        rows: data.rows || [],
        exportedAt: data.exported_at || null,
        rowsCount: data.rows_count || (data.rows ? data.rows.length : 0),
        fromFallback: false
      };
    } catch (err) {
      console.warn('[data-loader] falha ao carregar ' + url + ':', err.message);
      if (options.fallback !== undefined) {
        return {
          ok: true,
          data: { rows: options.fallback, _fallback: true },
          rows: options.fallback,
          exportedAt: null,
          rowsCount: options.fallback.length,
          fromFallback: true,
          error: err.message
        };
      }
      return { ok: false, data: null, rows: [], error: err.message, fromFallback: false };
    }
  }

  // Mostra pequeno selo "última sync" ou "modo demo" no header
  function syncBadge(elementId, result){
    const el = typeof elementId === 'string' ? document.getElementById(elementId) : elementId;
    if (!el) return;
    if (result.fromFallback) {
      el.textContent = '⚠ Modo demo · dados estáticos';
      el.title = 'Falha ao carregar pipeline real: ' + (result.error || '');
      el.style.color = 'var(--ambar, #a86d1f)';
      return;
    }
    if (result.exportedAt) {
      const d = new Date(result.exportedAt);
      const dd = String(d.getDate()).padStart(2,'0');
      const mm = String(d.getMonth()+1).padStart(2,'0');
      const hh = String(d.getHours()).padStart(2,'0');
      const mi = String(d.getMinutes()).padStart(2,'0');
      el.textContent = 'Última sync · ' + dd + '/' + mm + ' · ' + hh + ':' + mi;
      el.style.color = '';
    } else {
      el.textContent = result.rowsCount + ' linhas carregadas';
    }
  }

  // Helpers de extração compatíveis com o schema da Volution (igual repo_widget.js)
  function getExpr(row, key){
    const e = row.expressions || {};
    const v = e[key];
    if (v === undefined || v === null) return 0;
    if (typeof v === 'object' && 'value' in v) return Number(v.value) || 0;
    return Number(v) || 0;
  }
  function getCode(row){
    return row.rootProductCode || row.productCode || row.code ||
           (row.product && (row.product.code || row.product.rootProductCode)) || '';
  }
  function getDesc(row){
    return row.rootProductName || row.productName || row.description ||
           (row.product && (row.product.name || row.product.description)) || '';
  }

  global.RoiDataLoader = {
    load: loadReport,
    syncBadge: syncBadge,
    getExpr: getExpr,
    getCode: getCode,
    getDesc: getDesc,
    BASE: BASE
  };
})(window);
