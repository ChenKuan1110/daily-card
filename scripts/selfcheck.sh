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

echo "  [1/8] Python 语法"
python3 -m py_compile cardgen.py cardconfig.py cardpreview.py server.py scripts/test_subpath.py
echo "        OK"

echo "  [2/8] 依赖与私有配置"
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

echo "  [3/8] 主题与平台清单"
python3 cardgen.py --list-themes > /dev/null
echo "        OK"

echo "  [4/8] 渲染冒烟"
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

echo "  [5/8] 私有数据未纳入版本管理"
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

echo "  [6/8] 前端脚本语法"
if command -v node >/dev/null 2>&1; then
  node --check web/app.js
  echo "        OK"
else
  echo "        跳过（未安装 node）"
fi

echo "  [7/8] 前端路径可移植性"
python3 - <<'PYEOF'
import re
import pathlib

js = pathlib.Path("web/app.js").read_text(encoding="utf-8")
html = pathlib.Path("web/index.html").read_text(encoding="utf-8")
assert "const BASE" in js and "const url" in js, "缺少运行时 BASE"
assert "await fetch(url(path), opt)" in js, "fetch 未走 url()"
bad = []
for name, text in (("app.js", js), ("index.html", html)):
    for pat in (r'(?:src|href)\s*=\s*"/', r'"/api/', r"'/api/"):
        for m in re.finditer(pat, text):
            bad.append(name + ": " + m.group(0))
assert not bad, "发现硬编码绝对路径：" + "; ".join(bad)
print("        无硬编码绝对路径，请求统一经 url() 派生")
PYEOF
if command -v node >/dev/null 2>&1; then
  node - <<'JSEOF'
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync("web/app.js", "utf8");
const head = src.slice(0, src.indexOf("const $ ="));
function derive(baseURI, override) {
  const ctx = { window: override ? { DAILY_CARD_BASE: override } : {}, document: { baseURI }, URL };
  vm.createContext(ctx);
  vm.runInContext(head + "\nthis.out = url('api/bootstrap');", ctx);
  return ctx.out;
}
const cases = [
  ["http://host/daily-card/", undefined, "http://host/daily-card/api/bootstrap"],
  ["http://host/", undefined, "http://host/api/bootstrap"],
  ["http://host/daily-card/index.html", undefined, "http://host/daily-card/api/bootstrap"],
  ["http://host/daily-card/", "https://api.example.com/daily-card/", "https://api.example.com/daily-card/api/bootstrap"]
];
for (const [b, o, want] of cases) {
  const got = derive(b, o);
  if (got !== want) throw new Error("BASE 推导错误: " + b + " -> " + got + "，应为 " + want);
}
console.log("        BASE 推导 4 组用例通过（子路径 / 根路径 / 含文件名 / 覆盖口）");
JSEOF
else
  echo "        跳过 BASE 单测（未安装 node）"
fi

echo "  [8/8] 子路径部署模拟（nginx 剥前缀 + 静态分离）"
python3 scripts/test_subpath.py

echo "  自检全部通过"
