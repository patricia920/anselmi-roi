// @ts-check
/**
 * Smoke E2E tests pra anselmi-roi/vm/
 *
 * Roda contra produção (anselmi-roi.pages.dev/vm/) — não precisa de servidor local.
 * Use: npx playwright test tests/vm.smoke.spec.js
 *
 * Cobre o caminho crítico:
 *   1. Página carrega + título correto (não-JS)
 *   2. Sisplan (ved_varejo.js) parseia e popula VAR_LOJAS
 *   3. LOJA_MAP carrega + LOJAS reconstruído com slugs
 *   4. KPIs do header mostram números reais (não placeholders)
 *   5. Botão Excel chama exportLojaCSV e gera CSV válido
 *   6. /api/vm-state retorna 200 (KV bound)
 *   7. Fotos do photo.anselmi carregam (sem 404)
 *   8. Comparador de lojas abre e mostra KPIs
 *
 * Falha = regressão. Rodar antes de cada merge significativo.
 */
const { test, expect } = require('@playwright/test');

const URL_BASE = process.env.VM_URL || 'https://anselmi-roi.pages.dev/vm/';
const ORIGIN = URL_BASE.replace(/\/vm\/?$/, '');
const PASSWORD = process.env.VM_TEST_PASSWORD;

if (!PASSWORD) {
  console.warn('\n⚠️  VM_TEST_PASSWORD não setado — os testes vão falhar no middleware de auth.');
  console.warn('Defina antes de rodar:  export VM_TEST_PASSWORD=...\n');
}

// Login antes de cada teste — seta cookie auth_session via /api/login
test.beforeEach(async ({ page, context }) => {
  page.on('pageerror', err => console.log(`[browser-error] ${err.message}`));
  page.on('console', msg => {
    if (msg.type() === 'error' || msg.type() === 'warning') {
      console.log(`[browser-${msg.type()}] ${msg.text()}`);
    }
  });

  if (PASSWORD) {
    const r = await page.request.post(`${ORIGIN}/api/login`, {
      data: { password: PASSWORD },
      headers: { 'Content-Type': 'application/json' },
    });
    if (!r.ok()) {
      throw new Error(`Login falhou (${r.status()}): ${await r.text()}`);
    }
  }
});

test.describe('VM smoke', () => {
  test('1. Título e estrutura básica (HTML, não-JS)', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'commit' });
    await expect(page).toHaveTitle(/Anselmi VM/, { timeout: 15000 });
  });

  test('2. Sisplan carrega e popula VAR_LOJAS', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'load', timeout: 45000 });
    // Espera VAR_LOJAS aparecer (ved_varejo.js demora pra parsear no headless)
    await page.waitForFunction(
      () => typeof window.VAR_LOJAS === 'object' && window.VAR_LOJAS && Object.keys(window.VAR_LOJAS).length > 0,
      { timeout: 45000, polling: 500 }
    );
    const r = await page.evaluate(() => ({
      lojasCount: Object.keys(window.VAR_LOJAS).length,
      hasVarEstoque: typeof window.VAR_ESTOQUE === 'object' && Object.keys(window.VAR_ESTOQUE || {}).length > 0,
    }));
    expect(r.lojasCount).toBeGreaterThanOrEqual(20);
    expect(r.hasVarEstoque).toBe(true);
  });

  test('3. LOJA_MAP + LOJAS reconstruído com slugs', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'load', timeout: 45000 });
    await page.waitForFunction(
      () => window.LOJA_MAP && Object.keys(window.LOJA_MAP).length > 0 &&
            typeof LOJAS !== 'undefined' && LOJAS.find(l => l.cod === 'patio-batel')?.storeid === '0102',
      { timeout: 45000, polling: 500 }
    );
    const r = await page.evaluate(() => {
      const lojas = (typeof LOJAS !== 'undefined' && LOJAS) || [];
      return {
        lojaMapKeys: Object.keys(window.LOJA_MAP || {}).length,
        lojasCount: lojas.length,
        patioStoreid: lojas.find(l => l.cod === 'patio-batel')?.storeid,
      };
    });
    expect(r.lojaMapKeys).toBeGreaterThanOrEqual(18);
    expect(r.lojasCount).toBeGreaterThanOrEqual(18);
    expect(r.patioStoreid).toBe('0102');
  });

  test('4. KPIs do header com números reais', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'load', timeout: 45000 });
    await page.waitForFunction(() => {
      const v = document.getElementById('hdr-kpi-expostos')?.textContent;
      return v && v !== '—' && /\d/.test(v);
    }, { timeout: 45000, polling: 500 });
    const kpis = await page.evaluate(() => ({
      expostos: document.getElementById('hdr-kpi-expostos')?.textContent,
      buracos:  document.getElementById('hdr-kpi-buracos')?.textContent,
      cd:       document.getElementById('hdr-kpi-cd')?.textContent,
      paradas:  document.getElementById('hdr-kpi-paradas')?.textContent,
    }));
    expect(kpis.expostos).toMatch(/^[0-9.]+$/);
    expect(kpis.buracos).toMatch(/^[0-9.]+$/);
    expect(kpis.cd).toMatch(/^[0-9.]+$/);
    expect(kpis.paradas).toMatch(/^[0-9.]+$/);
    expect(parseInt(kpis.expostos.replace(/\./g,''), 10)).toBeGreaterThan(1000);
  });

  test('5. Excel export gera CSV com seções corretas', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'load', timeout: 45000 });
    await page.waitForFunction(() => {
      const l = (typeof LOJAS !== 'undefined' && LOJAS) || [];
      return l.find(x => x.cod === 'patio-batel')?.storeid === '0102' && typeof window.exportLojaCSV === 'function';
    }, { timeout: 45000, polling: 500 });

    const csv = await page.evaluate(async () => {
      const origAppend = document.body.appendChild.bind(document.body);
      let captured = null;
      document.body.appendChild = function(el){
        if (el && el.tagName === 'A' && el.download) { captured = el.href; return el; }
        return origAppend(el);
      };
      const origClick = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function(){};
      window.exportLojaCSV('patio-batel');
      document.body.appendChild = origAppend; HTMLAnchorElement.prototype.click = origClick;
      if (!captured) return null;
      const r = await fetch(captured);
      return await r.text();
    });

    expect(csv).toBeTruthy();
    expect(csv).toContain('# METADADOS');
    expect(csv).toContain('# MANEQUINS');
    expect(csv).toContain('# ARARAS');
    expect(csv).toContain('# PEÇAS NA LOJA');
    expect(csv).toContain('Storeid Sisplan;0102');
    expect(csv).toContain('Pátio Batel');
  });

  test('6. /api/vm-state retorna 200 com KV bound', async ({ page }) => {
    // Independente do JS — chama direto a Pages Function
    const r = await page.request.get(URL_BASE.replace(/\/vm\/?$/, '/api/vm-state?store=patio-batel'));
    expect(r.status()).toBe(200);
    const body = await r.json();
    expect(body).toHaveProperty('ok', true);
    expect(body).toHaveProperty('store', 'patio-batel');
    expect(JSON.stringify(body)).not.toContain('VM_STATE_KV não configurado');
  });

  test('7. Foto do photo.anselmi.ind.br carrega', async ({ page }) => {
    // Pega URL do banco_fotos direto, sem precisar do JS da página
    const bancoUrl = URL_BASE.replace(/\/vm\/?$/, '/data/banco_fotos.json');
    const r = await page.request.get(bancoUrl);
    expect(r.status()).toBe(200);
    const banco = await r.json();
    const fotos = banco.fotos || banco;
    const primeiraRef = Object.keys(fotos)[0];
    const primeiraCor = Object.keys(fotos[primeiraRef])[0];
    const primeiraUrl = fotos[primeiraRef][primeiraCor][0];
    expect(primeiraUrl).toMatch(/photo\.anselmi\.ind\.br/);
    const imgRes = await page.request.get(primeiraUrl);
    expect(imgRes.status()).toBe(200);
    expect(imgRes.headers()['content-type']).toContain('image');
  });

  test('8. Comparador de lojas abre e mostra KPIs', async ({ page }) => {
    await page.goto(URL_BASE, { waitUntil: 'load', timeout: 45000 });
    await page.waitForFunction(
      () => typeof window.openComparador === 'function' && window.LOJA_MAP && Object.keys(window.LOJA_MAP).length > 0,
      { timeout: 45000, polling: 500 }
    );
    await page.evaluate(() => window.openComparador());
    await page.waitForFunction(() => document.getElementById('cmp-overlay')?.classList.contains('show'), { timeout: 10000 });
    await expect(page.locator('#cmp-overlay')).toBeVisible();
    await expect(page.locator('.cmp-kpis .cmp-kpi')).toHaveCount(4);
  });
});
