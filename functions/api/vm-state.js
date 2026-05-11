/**
 * functions/api/vm-state.js
 * -------------------------
 * Cloudflare Pages Function — estado da página VM por loja.
 *
 * GET  /api/vm-state?store=BATEL   → retorna o último estado salvo daquela loja
 * POST /api/vm-state?store=BATEL   → salva novo estado (body = JSON)
 *
 * Persistência: Cloudflare KV (env binding VM_STATE_KV).
 * Chave: "store:{storeKey}"  (uma chave por loja, sobrescreve)
 * Histórico: "history:{storeKey}:{ts}"  (TTL 30 dias, append-only)
 *
 * Segurança (basic):
 * - CORS restrito ao próprio origin (anselmi-roi.pages.dev e domínio custom)
 * - POST exige header Origin batendo com lista permitida (write protection)
 * - GET continua aberto (apenas leitura — não vaza nada sensível além do estado VM)
 *
 * Pra hardening completo: usar Cloudflare Access (Zero Trust) na rota /api/vm-state.
 */

const HISTORY_PREFIX = 'history:';
const MAX_HISTORY_TTL = 30 * 24 * 60 * 60; // 30d

const ALLOWED_ORIGINS = new Set([
  'https://anselmi-roi.pages.dev',
  'https://vm.anselmi.com.br',         // domínio custom (se/quando configurado)
  'https://anselmi.com.br',            // domínio principal
  'http://localhost:8788',              // wrangler pages dev
  'http://localhost:3000',              // alternativo dev
]);

function originOk(request) {
  const origin = request.headers.get('Origin') || '';
  // Permite same-origin (Origin não setado em alguns navegadores) ou origin allowlisted
  return !origin || ALLOWED_ORIGINS.has(origin) || origin.endsWith('.anselmi-roi.pages.dev');
}

function corsHeaders(request) {
  const origin = request?.headers?.get('Origin') || '';
  const allowOrigin = (origin && (ALLOWED_ORIGINS.has(origin) || origin.endsWith('.anselmi-roi.pages.dev')))
    ? origin
    : 'https://anselmi-roi.pages.dev';
  return {
    'Access-Control-Allow-Origin': allowOrigin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
}

function json(data, status = 200, request = null) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(request) },
  });
}

function getStoreKey(request) {
  const url = new URL(request.url);
  const raw = url.searchParams.get('store') || '';
  // sanitiza pra evitar bizarrice de chave KV
  const safe = raw.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 32);
  return safe || null;
}

export async function onRequestOptions({ request }) {
  return new Response(null, { status: 204, headers: corsHeaders(request) });
}

export async function onRequestGet({ request, env }) {
  if (!env.VM_STATE_KV) {
    return json({ ok: false, error: 'KV binding VM_STATE_KV não configurado' }, 500, request);
  }
  const storeKey = getStoreKey(request);
  if (!storeKey) {
    return json({ ok: false, error: 'parâmetro ?store= é obrigatório' }, 400, request);
  }
  try {
    const raw = await env.VM_STATE_KV.get('store:' + storeKey);
    if (!raw) return json({ ok: true, store: storeKey, state: null }, 200, request);
    const state = JSON.parse(raw);
    return json({
      ok: true,
      store: storeKey,
      state,
      savedAt: state._meta?.savedAt || null,
    }, 200, request);
  } catch (e) {
    return json({ ok: false, error: e.message }, 500, request);
  }
}

export async function onRequestPost({ request, env }) {
  if (!env.VM_STATE_KV) {
    return json({ ok: false, error: 'KV binding VM_STATE_KV não configurado' }, 500, request);
  }
  // Write protection: só aceita POST de origens permitidas
  if (!originOk(request)) {
    return json({ ok: false, error: 'origem não autorizada' }, 403, request);
  }
  const storeKey = getStoreKey(request);
  if (!storeKey) {
    return json({ ok: false, error: 'parâmetro ?store= é obrigatório' }, 400, request);
  }
  try {
    const body = await request.json();
    const wrapped = {
      ...body,
      _meta: {
        savedAt: new Date().toISOString(),
        store: storeKey,
        userAgent: request.headers.get('User-Agent') || 'unknown',
        origin: request.headers.get('Origin') || 'same-origin',
      },
    };
    const serialized = JSON.stringify(wrapped);

    await env.VM_STATE_KV.put('store:' + storeKey, serialized);

    const historyKey = `${HISTORY_PREFIX}${storeKey}:${Date.now()}`;
    await env.VM_STATE_KV.put(historyKey, serialized, { expirationTtl: MAX_HISTORY_TTL });

    return json({ ok: true, store: storeKey, savedAt: wrapped._meta.savedAt }, 200, request);
  } catch (e) {
    return json({ ok: false, error: e.message }, 500, request);
  }
}
