#!/usr/bin/env bash
# daily-card · 前端静态资源版本发布
#
# 版本目录 + current 符号链接；nginx 的 location /daily-card/ 用 alias
# 指向 <WEB_ROOT>/current/。只管理静态资源，不动后端与私有配置。
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
SRC="$ROOT/web"
WEB_ROOT="${DAILY_CARD_WEB_ROOT:-/opt/daily-card-web}"
KEEP="${DAILY_CARD_WEB_KEEP:-5}"

usage() {
  cat <<'EOF'
daily-card 前端静态资源发布

  ./scripts/publish-web.sh [version]          发布当前 web/（默认取 VERSION）
  ./scripts/publish-web.sh --list             列出已发布版本与当前指向
  ./scripts/publish-web.sh --rollback [ver]   回滚到指定版本，缺省为上一个
  ./scripts/publish-web.sh --help             显示本帮助

可选环境变量：
  DAILY_CARD_WEB_ROOT   静态版本根目录（默认 /opt/daily-card-web）
  DAILY_CARD_WEB_KEEP   保留的历史版本数（默认 5）

发布完成后 nginx 侧 reload 即可，静态资源走 ETag 协商缓存，刷新即生效。
EOF
}

die() { echo "错误：$*" >&2; exit 1; }

[ -f "$SRC/index.html" ] && [ -f "$SRC/app.js" ] && [ -f "$SRC/style.css" ] \
  || die "web/ 缺少 index.html / app.js / style.css"

versions() {
  [ -d "$WEB_ROOT" ] || return 0
  for d in "$WEB_ROOT"/v*; do
    [ -d "$d" ] || continue
    basename "$d"
  done | sort -r
}

current_version() {
  if [ -L "$WEB_ROOT/current" ]; then basename "$(readlink "$WEB_ROOT/current")"; fi
}

switch_link() {
  local target="$1" tmp
  tmp="$WEB_ROOT/.current.$$"
  rm -f "$tmp"
  ln -s "$target" "$tmp"
  # Linux 用 mv -T 原子替换符号链接；macOS 无 -T，退化为删链再建
  if [ "$(uname -s)" = "Linux" ] && mv -T --help >/dev/null 2>&1; then
    mv -fT "$tmp" "$WEB_ROOT/current"
  else
    rm -f "$WEB_ROOT/current"
    mv "$tmp" "$WEB_ROOT/current"
  fi
}

prune() {
  # 安全边界：只清理本脚本初始化过的根目录，且只删 v* 版本目录
  [ -f "$WEB_ROOT/.daily-card-web-root" ] || { echo "跳过清理（根目录无标记）"; return; }
  local cur i=0 v
  cur="$(current_version)"
  while read -r v; do
    [ -n "$v" ] || continue
    [ "$v" = "$cur" ] && continue
    i=$((i + 1))
    if [ "$i" -gt "$KEEP" ]; then
      rm -rf "$WEB_ROOT/$v"
      echo "  清理旧版本：$v"
    fi
  done < <(versions)
}

publish() {
  local ver="$1" target tmp
  [[ "$ver" =~ ^[A-Za-z0-9._-]+$ ]] || die "版本名只允许字母、数字、点、下划线、连字符"
  case "$ver" in v*) ;; *) ver="v$ver" ;; esac
  target="$WEB_ROOT/$ver"
  mkdir -p "$WEB_ROOT"
  touch "$WEB_ROOT/.daily-card-web-root"
  tmp="$WEB_ROOT/.stage.$$"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  cp -R "$SRC"/. "$tmp"/
  cat > "$tmp/manifest.json" <<EOF
{
  "version": "$ver",
  "published_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source_commit": "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)",
  "files": ["index.html", "app.js", "style.css"]
}
EOF
  rm -rf "$target"
  mv "$tmp" "$target"
  switch_link "$target"
  echo "  已发布：$ver → $target"
  echo "  当前指向：$(current_version)"
  prune
  echo
  echo "  nginx alias 应指向：$WEB_ROOT/current/"
}

rollback() {
  local want="$1" cur
  [ -d "$WEB_ROOT" ] || die "尚未发布任何版本"
  cur="$(current_version)"
  if [ -z "$want" ]; then
    want="$(versions | grep -v "^${cur:-__none__}$" | head -1 || true)"
  else
    case "$want" in v*) ;; *) want="v$want" ;; esac
  fi
  [ -n "$want" ] || die "没有可回滚的版本"
  [ -d "$WEB_ROOT/$want" ] || die "版本不存在：$want"
  switch_link "$WEB_ROOT/$want"
  echo "  已回滚：${cur:-未发布} → $want"
  echo "  nginx 无需改动，reload 后生效"
}

list() {
  echo "  根目录：$WEB_ROOT"
  echo "  当前指向：$(current_version || echo 未发布)"
  echo "  已发布版本："
  versions | sed 's/^/    /'
}

case "${1:-}" in
  --help|-h)   usage; exit 0 ;;
  --list)      list; exit 0 ;;
  --rollback)  shift; rollback "${1:-}"; exit 0 ;;
  --*)         die "未知参数：$1" ;;
  *)           publish "${1:-$(cat "$ROOT/VERSION" 2>/dev/null || echo dev)}" ;;
esac
