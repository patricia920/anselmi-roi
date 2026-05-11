/**
 * _middleware.js
 * --------------
 * Roda em TODAS as requests do anselmi-roi.pages.dev.
 * Protege o site com senha compartilhada via cookie de sessão.
 *
 * Rotas públicas (sem auth):
 *   - /login           (página de login)
 *   - /api/login       (POST: valida senha, seta cookie)
 *   - /api/logout      (POST: limpa cookie)
 *   - /lib/auth.js     (script da página de login)
 *
 * Resto: redireciona pra /login se cookie inválido/ausente.
 *
 * Cookie: `auth_session` HttpOnly, Secure, SameSite=Lax, 24h
 * Valor: HMAC-SHA256 do timestamp+secret (sem JWT pra simplicidade)
 */

const COOKIE_NAME = 'auth_session';
const SESSION_DURATION_MS = 24 * 60 * 60 * 1000; // 24h

const PUBLIC_PATHS = [
  '/login',
  '/login.html',
  '/api/login',
  '/api/logout',
  '/lib/auth.js',
  '/favicon.ico',
];

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

async function isValidSession(cookieValue, secret) {
  if (!cookieValue || !secret) return false;
  const parts = cookieValue.split('.');
  if (parts.length !== 2) return false;
  const [issuedAt, signature] = parts;
  const ts = parseInt(issuedAt, 10);
  if (!ts || Date.now() - ts > SESSION_DURATION_MS) return false;
  const expectedSig = await hmac(secret, String(ts));
  return signature === expectedSig;
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const url = new URL(request.url);

  // Rotas públicas passam livre
  if (PUBLIC_PATHS.some(p => url.pathname === p || url.pathname.startsWith(p + '/'))) {
    return next();
  }

  // Verifica cookie
  const cookies = (request.headers.get('Cookie') || '')
    .split(';').map(c => c.trim()).reduce((acc, c) => {
      const [k, v] = c.split('=');
      if (k) acc[k] = v;
      return acc;
    }, {});

  const session = cookies[COOKIE_NAME];
  const valid = await isValidSession(session, env.AUTH_SECRET);

  if (valid) {
    return next();
  }

  // Não autenticado — redireciona pra /login (preserva pathname original como ?next=)
  const loginUrl = new URL('/login', url.origin);
  loginUrl.searchParams.set('next', url.pathname + url.search);
  return Response.redirect(loginUrl.toString(), 302);
}
