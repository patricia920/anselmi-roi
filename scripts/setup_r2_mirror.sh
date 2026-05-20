#!/bin/bash
# setup_r2_mirror.sh — guia interativo pra ativar o mirror Cloudflare R2.
# Rodar no Mac da Pati. Abre URLs do CF + GitHub e seta os 5 secrets via gh CLI.
#
# Pré-requisitos no Mac:
#   - Chrome instalado
#   - gh CLI:  brew install gh && gh auth login
#
# Uso: bash setup_r2_mirror.sh

set -e

PCP_REPO="patricia920/anselmi-pcp"
ROI_REPO="patricia920/anselmi-roi"

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Setup do mirror Cloudflare R2 (Anselmi VM)"
echo "════════════════════════════════════════════════════════════"
echo ""

# Checa gh CLI
if ! command -v gh &> /dev/null; then
  echo "❌ gh CLI não encontrado. Instala:  brew install gh && gh auth login"
  exit 1
fi
if ! gh auth status &> /dev/null; then
  echo "❌ gh não autenticado. Roda:  gh auth login"
  exit 1
fi
echo "✓ gh CLI OK"
echo ""

# ─── 1. CLOUDFLARE R2: criar bucket ──────────────────────────
echo "─────────────────────────────────────────────────"
echo "PASSO 1/4: Criar bucket R2 no Cloudflare"
echo "─────────────────────────────────────────────────"
echo ""
echo "Vou abrir o Cloudflare R2. Você precisa:"
echo "  a) Aceitar termos do R2 (se primeiro acesso)"
echo "  b) Create bucket → nome: anselmi-fotos-mirror"
echo "  c) Location hint: North America (mais perto do CF Pages)"
echo "  d) Dentro do bucket → Settings → Public Access → Allow Access"
echo "     (gera URL https://pub-XXX.r2.dev — anota!)"
echo ""
read -p "[Enter] pra abrir o Cloudflare R2..."
open -a "Google Chrome" "https://dash.cloudflare.com/?to=/:account/r2/overview"

echo ""
read -p "Cole aqui a URL pública do bucket (https://pub-XXX.r2.dev): " R2_PUBLIC_BASE
R2_PUBLIC_BASE="${R2_PUBLIC_BASE%/}"  # remove trailing slash
[ -z "$R2_PUBLIC_BASE" ] && { echo "❌ URL vazia, abortando"; exit 1; }
echo "✓ R2_PUBLIC_BASE=$R2_PUBLIC_BASE"

# ─── 2. CLOUDFLARE R2: API token ─────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "PASSO 2/4: Gerar API Token R2"
echo "─────────────────────────────────────────────────"
echo ""
echo "Vou abrir 'Manage R2 API Tokens'. Você precisa:"
echo "  a) Create API Token"
echo "  b) Name: anselmi-mirror-bot"
echo "  c) Permissions: Object Read & Write"
echo "  d) Specify bucket: anselmi-fotos-mirror"
echo "  e) TTL: forever (deixa em branco)"
echo "  f) Create → copia Access Key ID, Secret Access Key, Endpoint"
echo ""
read -p "[Enter] pra abrir Manage R2 API Tokens..."
open -a "Google Chrome" "https://dash.cloudflare.com/?to=/:account/r2/api-tokens"

echo ""
read -p "Access Key ID: " R2_ACCESS_KEY_ID
read -p "Secret Access Key: " R2_SECRET_ACCESS_KEY
read -p "Endpoint (https://<account-id>.r2.cloudflarestorage.com): " R2_ENDPOINT
R2_ENDPOINT="${R2_ENDPOINT%/}"
[ -z "$R2_ACCESS_KEY_ID" ] || [ -z "$R2_SECRET_ACCESS_KEY" ] || [ -z "$R2_ENDPOINT" ] && {
  echo "❌ campos vazios, abortando"; exit 1
}
echo "✓ token R2 capturado"

# ─── 3. GITHUB PAT pro anselmi-roi ───────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "PASSO 3/4: Criar PAT pro mirror clonar o anselmi-roi"
echo "─────────────────────────────────────────────────"
echo ""
echo "Vou abrir GitHub PAT settings. Você precisa:"
echo "  a) Fine-grained tokens → Generate new token"
echo "  b) Name: roi-read-for-mirror"
echo "  c) Expiration: 1 year"
echo "  d) Repository access: Only select repositories → anselmi-roi"
echo "  e) Repository permissions: Contents = Read-only"
echo "  f) Generate → copia o token (começa com github_pat_)"
echo ""
read -p "[Enter] pra abrir GitHub PAT settings..."
open -a "Google Chrome" "https://github.com/settings/personal-access-tokens/new"

echo ""
read -p "PAT (github_pat_...): " ROI_PAT
[ -z "$ROI_PAT" ] && { echo "❌ PAT vazio, abortando"; exit 1; }
echo "✓ PAT capturado"

# ─── 4. SET SECRETS via gh CLI ───────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "PASSO 4/4: Setando 5 secrets no anselmi-pcp via gh CLI"
echo "─────────────────────────────────────────────────"
echo ""

echo "$R2_ACCESS_KEY_ID"     | gh secret set R2_ACCESS_KEY_ID     -R "$PCP_REPO" && echo "✓ R2_ACCESS_KEY_ID"
echo "$R2_SECRET_ACCESS_KEY" | gh secret set R2_SECRET_ACCESS_KEY -R "$PCP_REPO" && echo "✓ R2_SECRET_ACCESS_KEY"
echo "$R2_ENDPOINT"          | gh secret set R2_ENDPOINT          -R "$PCP_REPO" && echo "✓ R2_ENDPOINT"
echo "$R2_PUBLIC_BASE"       | gh secret set R2_PUBLIC_BASE       -R "$PCP_REPO" && echo "✓ R2_PUBLIC_BASE"
echo "$ROI_PAT"              | gh secret set ROI_PAT              -R "$PCP_REPO" && echo "✓ ROI_PAT"

echo ""
echo "─────────────────────────────────────────────────"
echo "  ✅ Secrets configurados! Push dos workflows agora."
echo "─────────────────────────────────────────────────"
echo ""

PCP_LOCAL="$HOME/Documents/Claude/Projects/PCP/anselmi-pcp"
ROI_LOCAL="$HOME/Documents/Claude/Projects/ROI/_REPO_ANSELMI_ROI"

if [ -d "$PCP_LOCAL/.git" ]; then
  echo "→ Pushando anselmi-pcp (workflow mirror)..."
  cd "$PCP_LOCAL"
  git pull --rebase --quiet 2>&1 | tail -2
  git push 2>&1 | tail -2
fi

if [ -d "$ROI_LOCAL/.git" ]; then
  echo "→ Atualizando anselmi-roi sync_from_pcp..."
  cd "$ROI_LOCAL"
  git pull --rebase --quiet 2>&1 | tail -2
  if [ -f scripts/templates/sync_from_pcp.workflow.yml ]; then
    cp scripts/templates/sync_from_pcp.workflow.yml .github/workflows/sync_from_pcp.yml
    git add .github/workflows/sync_from_pcp.yml
    git commit -m "ci(sync): adiciona fotos_r2.json ao sparse-checkout" 2>&1 | tail -2 || echo "  (sem mudanças no workflow)"
    git push 2>&1 | tail -2
  fi
fi

echo ""
echo "─────────────────────────────────────────────────"
echo "  🚀 Disparando primeiro mirror agora"
echo "─────────────────────────────────────────────────"
gh workflow run mirror_fotos_r2.yml -R "$PCP_REPO" && {
  echo "✓ Workflow disparado. Acompanha em:"
  echo "  https://github.com/$PCP_REPO/actions/workflows/mirror_fotos_r2.yml"
  echo ""
  echo "Primeira run: ~15-30min (baixa+sobe 42k fotos)."
  echo "Após terminar, o sync_from_pcp (30/30min) puxa fotos_r2.json pro anselmi-roi"
  echo "e o dashboard automaticamente passa a usar R2 como fonte primária."
}

echo ""
echo "Pronto! 🎉"
