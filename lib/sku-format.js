/**
 * sku-format.js
 * -------------
 * Formata referência de produto inserindo "_" depois dos 6 primeiros chars.
 *
 *   011739C25  → 011739_C25
 *   028871010  → 028871_010
 *   011739010M → 011739_010M
 *
 * Uso:
 *   window.fmtSku('011739C25')   // → '011739_C25'
 */
(function (global) {
  'use strict';

  function fmtSku(s) {
    if (s == null) return '';
    const str = String(s).trim();
    if (str.length <= 6) return str;
    return str.slice(0, 6) + '_' + str.slice(6);
  }

  global.fmtSku = fmtSku;
})(window);
