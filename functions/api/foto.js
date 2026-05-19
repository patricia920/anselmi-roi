/**
 * /api/foto?u=<filename>
 * -----------------------
 * Proxy de imagens do Zenphoto (photo.anselmi.ind.br) pra contornar
 * proteção anti-hotlinking baseada em Referer. O <img> do dashboard
 * pede /api/foto?u=11739_10.jpg, o Worker busca do Zenphoto SEM
 * mandar Referer (server-side fetch), devolve o blob com cache.
 *
 * Aceita só nomes de arquivo dentro de /Fotos/ — não permite path
 * traversal nem proxy pra outros domínios.
 *
 * Cache: 1 dia no edge (CF) + 1h no browser. Imagem é imutável em
 * princípio (Zenphoto não muda foto sob mesmo filename).
 */

const ZENPHOTO_BASE = 'https://photo.anselmi.ind.br/Fotos/';

// Padrões legítimos do banco_fotos: 11739_10.jpg, 011739_010.jpg,
// 11739_a98.jpg, 11739_C25.jpg. Bloqueia anything else.
const VALID_FILENAME = /^[0-9a-zA-Z_]{3,30}\.(jpg|jpeg|png|webp)$/i;

export async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);
  const u = url.searchParams.get('u') || '';

  if (!VALID_FILENAME.test(u)) {
    return new Response('Invalid filename', { status: 400 });
  }

  const upstream = ZENPHOTO_BASE + u;
  const cacheKey = new Request(upstream, { method: 'GET' });
  const cache = caches.default;

  // 1) Tenta cache primeiro
  let resp = await cache.match(cacheKey);
  if (resp) {
    // Repassa com cache-control pro browser
    const headers = new Headers(resp.headers);
    headers.set('X-Cache', 'HIT');
    return new Response(resp.body, { status: resp.status, headers });
  }

  // 2) Fetch upstream sem Referer (server-side, sem hotlink protection)
  // Debug mode: ?debug=1 retorna info sobre o upstream em vez da imagem
  const debug = url.searchParams.get('debug') === '1';
  try {
    const r = await fetch(upstream, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
      },
      redirect: 'follow',
    });

    if (debug) {
      const head = {};
      r.headers.forEach((v, k) => head[k] = v);
      return new Response(JSON.stringify({
        upstream,
        status: r.status,
        redirected: r.redirected,
        url: r.url,
        headers: head,
      }, null, 2), { headers: { 'Content-Type': 'application/json' } });
    }

    if (!r.ok) {
      // Upstream falhou: passa pelo status original + corpo do erro pro debug
      const errBody = await r.text().catch(() => '');
      return new Response(errBody.slice(0, 200) || ('Upstream ' + r.status), {
        status: r.status,
        headers: {
          'Cache-Control': r.status === 404 ? 'public, max-age=3600' : 'no-store',
          'Content-Type': 'text/plain',
          'X-Upstream-Status': String(r.status),
        },
      });
    }

    // 3) Sucesso: devolve com cache de 1 dia
    const buf = await r.arrayBuffer();
    const contentType = r.headers.get('content-type') || 'image/jpeg';
    const out = new Response(buf, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=86400, s-maxage=86400',
        'X-Cache': 'MISS',
      },
    });
    // Clona pra cache (response body só é lido 1x)
    await cache.put(cacheKey, out.clone());
    return out;
  } catch (e) {
    return new Response('Upstream error: ' + String(e), { status: 502 });
  }
}
