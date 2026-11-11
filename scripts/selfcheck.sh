#!/usr/bin/env bash
# daily-card · 健康自检（本地与 CI 共用入口）
# 只读检查 + 一次临时渲染，不写 output/、不改任何配置
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
TMP_PNG=""
cleanup() {
  if [ -n "$TMP_PNG" ] && [ -f "$TMP_PNG" ]; then rm -f "$TMP_PNG"; fi
}
trap cleanup EXIT

echo "  项目根：$ROOT"

echo "  [1/6] Python 语法"
python3 -m py_compile cardgen.py cardconfig.py cardpreview.py server.py
echo "        OK"

echo "  [2/6] 依赖与私有配置"
python3 - <<'PY'
import cardconfig as cfg
cfg.ensure_config()
t = cfg.load_themes()
r = cfg.load_registry()
s = cfg.load_settings()
assert t, "主题为空"
assert r.get("stickers"), "贴纸注册表为空"
print("        主题 %d 套 / 贴纸 %d 个 / 纹样 %d 种 / 默认平台 %s" % (
    len(t), len(r["stickers"]), len(r.get("motifs", [])), s.get("platform")))
PY

echo "  [3/6] 主题与平台清单"
python3 cardgen.py --list-themes > /dev/null
echo "        OK"

echo "  [4/6] 渲染冒烟"
TMP_PNG="$(mktemp "${TMPDIR:-/tmp}/dc-selfcheck-XXXXXX")"
python3 cardgen.py "自检卡片" "健康自检 · 冒烟渲染" \
  --platform moments --theme study --seed 7 --out "$TMP_PNG" > /dev/null
python3 - "$TMP_PNG" <<'PY'
import os, sys
from PIL import Image
p = sys.argv[1]
with Image.open(p) as im:
    im.verify()
with Image.open(p) as im:
    assert im.format == "PNG", "输出不是 PNG"
    print("        PNG %d x %d / %.0f KB" % (
        im.width, im.height, os.path.getsize(p) / 1024))
PY

echo "  [5/6] 私有数据未纳入版本管理"
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
  for f in config/themes.json config/settings.json .env; do
    if git check-ignore -q "$f"; then
      echo "        ignored: $f"
    else
      echo "        警告：$f 未被 .gitignore 忽略" >&2
    fi
  done
else
  echo "        跳过（非 git 工作树）"
fi

echo "  [6/6] 前端脚本语法"
if command -v node >/dev/null 2>&1; then
  node --check web/app.js
  echo "        OK"
else
  echo "        跳过（未安装 node）"
fi

echo "  自检全部通过"
