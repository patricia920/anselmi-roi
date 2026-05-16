/**
 * photo-frame.js
 * --------------
 * Detecta fotos cuja proporção real difere de 3:4 e adiciona a classe
 * `off-ratio` no container, pra renderizar uma "aba" creme lateral em vez
 * de cortar a foto.
 *
 * Como usar:
 * 1. Garantir que o container tem `aspect-ratio: 3/4` e CSS `.off-ratio { ... }`
 * 2. Incluir <script src="lib/photo-frame.js"></script>
 * 3. Adicionar `data-photo-frame` no container ou usar onload="window.__checkRatio(this)"
 *    no <img>.
 *
 * Tolerância: ±5% (entre 0.71 e 0.79).
 */
(function (global) {
  'use strict';

  function check(img) {
    if (!img || !img.naturalWidth || !img.naturalHeight) return;
    const ratio = img.naturalWidth / img.naturalHeight;
    const TARGET = 3 / 4; // 0.75
    const isOff = Math.abs(ratio - TARGET) > 0.05;
    if (img.parentElement) img.parentElement.classList.toggle('off-ratio', isOff);
  }

  // Observa o DOM pra pegar imgs adicionadas dinamicamente
  function setup() {
    // Já no DOM: aplica em todas as fotos dentro de containers com aspect-ratio 3/4
    document.querySelectorAll('[data-photo-frame] img, .cmp-thumb img, .ovs-thumb img, .t-thumb img, .drill-thumb img, .thumb img, .card-illust img').forEach(img => {
      if (img.complete && img.naturalWidth) check(img);
      else img.addEventListener('load', () => check(img), { once: true });
    });
  }

  global.__checkRatio = check;
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }
  // Re-aplica após cada potencial render (cliques que mudam a grid)
  global.__photoFrameRefresh = setup;
})(window);
