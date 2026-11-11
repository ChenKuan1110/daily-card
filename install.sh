#!/usr/bin/env bash
# daily-card · 幂等安装 / 更新脚本
# 可重复执行，不会覆盖已有的私有配置，也不会污染 output/
set -euo pipefail

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

LINK_SKILL=0
NO_DEPS=0

usage() {
  cat <<'EOF'
daily-card 安装 / 更新

  ./install.sh                 装依赖、初始化私有配置、跑自检
  ./install.sh --link-skill    额外把本机 skill 注册改为指向本仓库的符号链接
  ./install.sh --no-deps       跳过 pip 安装（已自行装好 Pillow 时用）
  ./install.sh --help          显示本帮助

可选环境变量：
  DAILY_CARD_CONFIG         私有配置目录（默认 <项目根>/config）
  DAILY_CARD_SKILLS_DIR     --link-skill 的目标 skills 目录
EOF
}

for arg in "$@"; do
  case "$arg" in
    --link-skill) LINK_SKILL=1 ;;
    --no-deps)    NO_DEPS=1 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "未知参数：$arg" >&2; usage >&2; exit 2 ;;
  esac
done

echo "daily-card 安装 / 更新"
echo "  项目根：$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：找不到 python3，请先安装 Python 3.9+" >&2
  exit 1
fi

echo
echo "[1/4] 依赖"
if [ "$NO_DEPS" -eq 1 ]; then
  echo "      跳过（--no-deps）"
elif python3 -c 'import PIL' >/dev/null 2>&1; then
  echo "      Pillow 已安装，跳过"
else
  python3 -m pip install -r requirements.txt
fi

echo
echo "[2/4] 私有配置初始化（已存在则保持不变）"
python3 - <<'PY'
import os
import cardconfig as cfg

had_t = os.path.exists(cfg.themes_file())
had_s = os.path.exists(cfg.settings_file())
cfg.ensure_config()
print("      配置目录：%s" % cfg.config_dir())
print("      themes.json   %s" % ("已存在，保持不变" if had_t else "已从出厂模板生成"))
print("      settings.json %s" % ("已存在，保持不变" if had_s else "已写入默认值"))
print("      主题 %d 套 / 贴纸 %d 个" % (
    len(cfg.load_themes()), len(cfg.load_registry()["stickers"])))
PY

echo
if [ "$LINK_SKILL" -eq 1 ]; then
  echo "[3/4] 建立 skill 符号链接"
  SKILLS_DIR="${DAILY_CARD_SKILLS_DIR:-}"
  if [ -z "$SKILLS_DIR" ]; then
    for d in "$HOME/.workbuddy/skills" "$HOME/.claude/skills" \
             "$HOME/.agents/skills" "$HOME/.codex/skills" \
             "$HOME/.config/opencode/skills"; do
      if [ -d "$d" ]; then SKILLS_DIR="$d"; break; fi
    done
  fi
  if [ -z "$SKILLS_DIR" ]; then
    echo "      未找到 skills 目录，跳过。可设 DAILY_CARD_SKILLS_DIR 指定。"
  else
    TARGET="$SKILLS_DIR/daily-card"
    if [ -L "$TARGET" ]; then
      CUR="$(readlink "$TARGET")"
      if [ "$CUR" = "$ROOT" ]; then
        echo "      已指向本仓库，无需改动：$TARGET"
      else
        echo "      已存在指向别处的软链：$TARGET -> $CUR" >&2
        echo "      脚本不擅自覆盖，请手动确认后再处理。" >&2
      fi
    elif [ -d "$TARGET" ]; then
      BAK="${TARGET}.backup-$(date +%Y%m%d-%H%M%S)"
      mv "$TARGET" "$BAK"
      ln -s "$ROOT" "$TARGET"
      echo "      原目录已备份为：$BAK"
      echo "      已建立：$TARGET -> $ROOT"
    elif [ -e "$TARGET" ]; then
      echo "      $TARGET 是普通文件，脚本不擅自处理，跳过。" >&2
    else
      mkdir -p "$SKILLS_DIR"
      ln -s "$ROOT" "$TARGET"
      echo "      已建立：$TARGET -> $ROOT"
    fi
  fi
else
  echo "[3/4] 跳过 skill 软链（需要时加 --link-skill）"
fi

echo
echo "[4/4] 健康自检"
"$ROOT/scripts/selfcheck.sh"

echo
echo "完成。接下来："
echo "  python3 cardgen.py \"标题\" \"副标题\"     # 直接出图，无需服务"
echo "  python3 server.py                       # 可选：启动网页后台"
echo "  git pull && ./install.sh                # 以后更新（私有配置不变）"
echo "  ./scripts/publish-web.sh              # 云服务器：发布前端静态版本（子路径部署）"
