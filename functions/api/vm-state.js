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
 * CORS aberto (mesmo padrão de /api/params).
 */

const HISTORY_PREFIX = 'history:';
const MAX_HISTORY_TTL = 30 * 24 * 60 * 60; // 30d

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

function getStoreKey(request) {
  const url = new URL(request.url);
  const raw = url.searchParams.get('store') || '';
  // sanitiza pra evitar bizarrice de chave KV
  const safe = raw.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 32);
  return safe || null;
}

export async function onRequestOptions() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function onRequestGet({ request, env }) {
  if (!env.VM_STATE_KV) {
    return json({ ok: false, error: 'KV binding VM_STATE_KV não configurado' }, 500);
  }
  const storeKey = getStoreKey(request);
  if (!storeKey) {
    return json({ ok: false, error: 'parâmetro ?store= é obrigatório' }, 400);
  }
  try {
    const raw = await env.VM_STATE_KV.get('store:' + storeKey);
    if (!raw) return json({ ok: true, store: storeKey, state: null });
    const state = JSON.parse(raw);
    return json({
      ok: true,
      store: storeKey,
      state,
      savedAt: state._meta?.savedAt || null,
    });
  } catch (e) {
    return json({ ok: false, error: e.message }, 500);
  }
}

export async function onRequestPost({ request, env }) {
  if (!env.VM_STATE_KV) {
    return json({ ok: false, error: 'KV binding VM_STATE_KV não configurado' }, 500);
  }
  const storeKey = getStoreKey(request);
  if (!storeKey) {
    return json({ ok: false, error: 'parâmetro ?store= é obrigatório' }, 400);
  }
  try {
    const body = await request.json();
    const wrapped = {
      ...body,
      _meta: {
        savedAt: new Date().toISOString(),
        store: storeKey,
        userAgent: request.headers.get('User-Agent') || 'unknown',
      },
    };
    const serialized = JSON.stringify(wrapped);

    await env.VM_STATE_KV.put('store:' + storeKey, serialized);

    const historyKey = `${HISTORY_PREFIX}${storeKey}:${Date.now()}`;
    await env.VM_STATE_KV.put(historyKey, serialized, { expirationTtl: MAX_HISTORY_TTL });

    return json({ ok: true, store: storeKey, savedAt: wrapped._meta.savedAt });
  } catch (e) {
    return json({ ok: false, error: e.message }, 500);
  }
}
