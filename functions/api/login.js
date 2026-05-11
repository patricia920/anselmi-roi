/**
 * POST /api/login
 * Body: {"password": "..."}
 * Compara com env.SHARED_PASSWORD. Se OK, seta cookie de sessão HMAC-assinado.
 */

const COOKIE_NAME = 'auth_session';
const SESSION_DURATION_S = 24 * 60 * 60; // 24h em segundos

async function hmac(secret, message) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return Array.from(new Uint8Array(sig))
    .map(b => b.toString(16).padStart(2, '0')).join('');
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
}

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
  });
}

export async function onRequestPost({ request, env }) {
  if (!env.SHARED_PASSWORD || !env.AUTH_SECRET) {
    return json({ ok: false, error: 'Auth não configurado (SHARED_PASSWORD/AUTH_SECRET ausentes)' }, 500);
  }
  let body;
  try { body = await request.json(); }
  catch { return json({ ok: false, error: 'JSON inválido' }, 400); }

  const password = body && body.password;
  if (!password || typeof password !== 'string') {
    return json({ ok: false, error: 'Senha obrigatória' }, 400);
  }
  if (!timingSafeEqual(password, env.SHARED_PASSWORD)) {
    // Delay artificial pra desencorajar brute force
    await new Promise(r => setTimeout(r, 600));
    return json({ ok: false, error: 'Senha inválida' }, 401);
  }

  // Gera cookie assinado: timestamp.hmac(timestamp)
  const ts = String(Date.now());
  const sig = await hmac(env.AUTH_SECRET, ts);
  const cookieValue = `${ts}.${sig}`;
  const cookie = `${COOKIE_NAME}=${cookieValue}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_DURATION_S}`;
  return json({ ok: true }, 200, { 'Set-Cookie': cookie });
}

export async function onRequestGet() {
  return json({ ok: false, error: 'Use POST com {"password": "..."}' }, 405);
}
