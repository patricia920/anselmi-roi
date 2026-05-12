# ADR-02: Auth via cookie HMAC custom

**Status:** Aceito
**Data:** 2026-05-11
**Deciders:** Pati (Anselmi)

## Contexto

O `anselmi-roi.pages.dev` contém dados sensíveis da operação (estoque, vendas
por loja, refs, plantas internas das lojas). Precisa de mecanismo de proteção
contra acesso público enquanto a equipe interna mantém acesso fácil.

Restrições:
- App é estático servido por Cloudflare Pages (sem backend dedicado)
- Equipe pequena (≤15 pessoas), sem provisioning IdP corporativo
- Não rolam crachás digitais corporativos (Google Workspace nem Azure AD na Anselmi)

## Decisão

**Senha compartilhada com cookie HMAC** em `functions/_middleware.js`:

- POST `/api/login` valida `{password}` contra `env.SHARED_PASSWORD`
- Sucesso → seta cookie `auth_session=<timestamp>.<hmac(timestamp)>` HttpOnly,
  Secure, SameSite=Lax, 24h
- `_middleware.js` valida cookie em **todas as requests** (whitelist: `/login`,
  `/api/login`, `/api/logout`, `/lib/auth.js`, `/favicon.ico`)
- HMAC-SHA256 com `env.AUTH_SECRET` (32+ chars), comparação timing-safe
- POST `/api/logout` limpa cookie

## Opções Consideradas

### A) Cookie HMAC custom (escolhida)
**Prós:** zero dependência externa, custo zero, controle total, ≤80 linhas de código.
**Contras:** senha única (todo mundo usa a mesma), não tem audit log per-user, não rotaciona automaticamente.

### B) Cloudflare Access (Zero Trust)
**Prós:** SSO Google/email magic link, audit log per-user, granular policies.
**Contras:** Free tier limita a 50 users (ok), mas precisa Anselmi configurar IdP (custo organizacional alto pra MVP), bloqueia automação (Playwright headless precisa Service Token).

### C) Cloudflare Pages Access nativo
**Prós:** integrado com Pages, sem código.
**Contras:** ainda em beta na época, mesmas limitações do CF Access.

### D) Sem auth
**Prós:** zero setup.
**Contras:** dados internos da operação públicos, vazamento de informação competitiva.

## Trade-offs

**Senha única vs IdP** — pra equipe de ≤15 pessoas com baixa rotatividade,
senha compartilhada é "suficiente". Cada saída/entrada na equipe → rotaciona
senha (`SHARED_PASSWORD` env var) + comunica via canal interno.

**Audit log** — não tem per-user, mas tem `_meta.userAgent + savedAt + origin`
nos writes do `/api/vm-state`, suficiente pra forensic básico.

**Cookie de 24h** — balança entre conveniência (não pede senha toda hora) e
segurança (laptop perdido revoga acesso em ≤24h).

## Consequências

- ✅ Site protegido publicamente (curl ou bot anônimo → redirect /login)
- ✅ Equipe entra com 1 senha compartilhada que lembra
- ⚠️ Playwright headless (CI) precisa secret `VM_TEST_PASSWORD` pra logar
- ⚠️ Rotação de senha exige edit no Cloudflare Pages env + redeploy
- ⚠️ Migrar pra Cloudflare Access se equipe crescer >30 ou regulamento exigir audit per-user

## Ações

- [x] Implementar `_middleware.js` + `/api/login` + `/api/logout`
- [x] Setar `SHARED_PASSWORD` e `AUTH_SECRET` no Cloudflare Pages env
- [x] Allowlist CORS em `/api/vm-state` (ALLOWED_ORIGINS)
- [ ] Documentar processo de rotação no CLAUDE.md
- [ ] Considerar migração pra CF Access se equipe ultrapassar 30 users
