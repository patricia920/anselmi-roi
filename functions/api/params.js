/**
 * functions/api/params.js
 * -----------------------
 * Cloudflare Pages Function — API de parâmetros do ROI clone.
 *
 * GET  /api/params      → retorna o último estado salvo (JSON)
 * POST /api/params      → salva novo estado (body = JSON)
 *
 * Persistência: Cloudflare KV (env binding PARAMS_KV).
 * Chave única no KV: "current" (sobrescreve a cada save).
 * Histórico: "history:{timestamp}" — append-only pra auditoria.
 *
 * CORS: aberto pra qualquer origin (mesmo projeto, mesmo subdomain).
 */

const KV_KEY = 'current';
const HISTORY_PREFIX = 'history:';
const MAX_HISTORY = 50;

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

export async function onRequestOptions() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function onRequestGet({ env }) {
  if (!env.PARAMS_KV) {
    return json({ ok: false, error: 'KV binding PARAMS_KV não configurado' }, 500);
  }
  try {
    const raw = await env.PARAMS_KV.get(KV_KEY);
    if (!raw) return json({ ok: true, state: null, message: 'sem estado salvo ainda' });
    const state = JSON.parse(raw);
    return json({ ok: true, state, savedAt: state._meta?.savedAt || null });
  } catch (e) {
    return json({ ok: false, error: e.message }, 500);
  }
}

export async function onRequestPost({ request, env }) {
  if (!env.PARAMS_KV) {
    return json({ ok: false, error: 'KV binding PARAMS_KV não configurado' }, 500);
  }
  try {
    const body = await request.json();
    // Envelope com metadados
    const wrapped = {
      ...body,
      _meta: {
        savedAt: new Date().toISOString(),
        userAgent: request.headers.get('User-Agent') || 'unknown',
      },
    };
    const serialized = JSON.stringify(wrapped);

    // Sobrescreve current
    await env.PARAMS_KV.put(KV_KEY, serialized);

    // Append no histórico (com TTL de 30 dias = 2592000s)
    const historyKey = HISTORY_PREFIX + Date.now();
    await env.PARAMS_KV.put(historyKey, serialized, { expirationTtl: 30 * 24 * 60 * 60 });

    return json({ ok: true, savedAt: wrapped._meta.savedAt });
  } catch (e) {
    return json({ ok: false, error: e.message }, 500);
  }
}
