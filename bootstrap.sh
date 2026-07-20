#!/usr/bin/env bash
# gyaku-beam 初回デプロイ: GitHubプライベートリポジトリ作成 → push → Pages有効化。
# 冪等: 既存リポジトリ・既存Pagesがあればスキップして続行する。
# 使い方: ./bootstrap.sh [リポジトリ名]   (省略時は推測不能なランダム名を生成)
set -euo pipefail
cd "$(dirname "$0")"

command -v gh >/dev/null || { echo "NG: gh CLI が必要です (brew install gh)"; exit 1; }
gh auth status >/dev/null || { echo "NG: gh auth login してください"; exit 1; }

OWNER=$(gh api user -q .login)

# ── リポジトリ名の決定 (推測不能な名前) ──
NAME_FILE=".repo-name"
if [ $# -ge 1 ]; then
  REPO_NAME="$1"
elif [ -f "$NAME_FILE" ]; then
  REPO_NAME=$(cat "$NAME_FILE")
else
  REPO_NAME="gb-$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 12)"
fi
echo "$REPO_NAME" > "$NAME_FILE"
echo "リポジトリ: $OWNER/$REPO_NAME"

# ── git 初期化・コミット ──
git rev-parse --git-dir >/dev/null 2>&1 || git init
git branch -M main 2>/dev/null || true
if ! git diff --quiet || ! git diff --cached --quiet || [ -z "$(git rev-list -n1 HEAD 2>/dev/null)" ]; then
  git add -A
  git commit -m "bootstrap" || true
fi

# ── リポジトリ作成 (冪等) ──
if gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  echo "リポジトリは既に存在 — スキップ"
else
  gh repo create "$OWNER/$REPO_NAME" --private
fi
git remote get-url origin >/dev/null 2>&1 || git remote add origin "git@github.com:$OWNER/$REPO_NAME.git"
git push -u origin main

# ── Pages 有効化 (build_type=workflow, 冪等) ──
if gh api "repos/$OWNER/$REPO_NAME/pages" >/dev/null 2>&1; then
  echo "Pagesは既に有効 — スキップ"
else
  gh api -X POST "repos/$OWNER/$REPO_NAME/pages" -f build_type=workflow
fi

# ── Discord Webhook (任意) ──
if [ -n "${DISCORD_WEBHOOK_URL:-}" ]; then
  gh secret set DISCORD_WEBHOOK_URL --repo "$OWNER/$REPO_NAME" --body "$DISCORD_WEBHOOK_URL"
  echo "DISCORD_WEBHOOK_URL を登録した"
else
  echo "(任意) Discord通知: DISCORD_WEBHOOK_URL=... ./bootstrap.sh で登録できます"
fi

# ── 初回デプロイ ──
gh workflow run pages.yml --repo "$OWNER/$REPO_NAME" --ref main 2>/dev/null || true

echo ""
echo "完了。URL: https://$OWNER.github.io/$REPO_NAME/"
echo "(初回デプロイは Actions の pages 完了後に反映)"
