/**
 * GET /api/sso-token
 * ------------------
 * Gera token HMAC pra autenticar o user no anselmi-producao sem nova senha.
 * Usado pelo iframe da aba PCP no vm/index.html.
 *
 * Token = base64url(timestamp + "." + HMAC-SHA256(timestamp + ROI_PCP_SSO_SECRET))
 * TTL: 5 minutos (curto pra reduzir risco se token vazar)
 *
 * Pré-requisito: env.ROI_PCP_SSO_SECRET — mesmo valor configurado em ambos os
 * Cloudflare Pages projects (anselmi-roi + anselmi-producao). 32+ chars random.
 *
 * Segurança: o _middleware.js já protege essa rota — só usuários com cookie
 * auth_session válido (logados no ROI) chegam aqui.
 */
const TOKEN_TTL_S = 300; // 5 minutos

async function hmacSha256(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return btoa(String.fromCharCode(...new Uint8Array(sig)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function onRequest(context) {
  const { env } = context;
  if (!env.ROI_PCP_SSO_SECRET) {
    return new Response(JSON.stringify({ error: 'ROI_PCP_SSO_SECRET not configured' }), {
      status: 501, headers: { 'Content-Type': 'application/json' }
    });
  }
  const ts = Math.floor(Date.now() / 1000);
  const exp = ts + TOKEN_TTL_S;
  const message = `${ts}.${exp}`;
  const sig = await hmacSha256(env.ROI_PCP_SSO_SECRET, message);
  const token = `${ts}.${exp}.${sig}`;

  return new Response(JSON.stringify({ token, expires_at: exp }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
    }
  });
}
