#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily-card 配置中心

所有主题、配色、贴纸注册表、全局设置都以 JSON 文件存放在 config/ 下：
  themes.default.json   出厂主题模板（只读，用于「恢复默认」）
  themes.json           运行时主题配置（后台可编辑，脚本实际读取这份）
  stickers.json         贴纸 / 纹样注册表（供 GUI 展示与校验）
  settings.json         默认平台、落款、超采样、颗粒度、输出目录等

另外提供从背景图提取「多套候选配色方案」的能力，供 CLI 与网页后台共用。
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import tempfile

from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_DIR = os.path.join(BASE, "config")
COLOR_KEYS = ["bg1", "bg2", "card", "ink", "sub", "accent",
              "accent2", "soft", "pill", "pill_text"]

_override_dir = None


def set_config_dir(path):
    global _override_dir
    _override_dir = os.path.abspath(path) if path else None


def config_dir():
    return _override_dir or os.environ.get("DAILY_CARD_CONFIG") or DEFAULT_CONFIG_DIR


def _path(name):
    return os.path.join(config_dir(), name)


def themes_file():
    return _path("themes.json")


def defaults_file():
    return _path("themes.default.json")


def settings_file():
    return _path("settings.json")


def registry_file():
    return _path("stickers.json")


def output_dir():
    return os.path.join(BASE, load_settings().get("output_dir", "output"))


def uploads_dir():
    d = os.path.join(BASE, "uploads")
    os.makedirs(d, exist_ok=True)
    return d


DEFAULT_SETTINGS = {
    "version": 1, "platform": "xhs", "brand": "", "date_mode": "today",
    "seed": None, "supersample": 2, "grain": 9,
    "output_dir": "output", "bg_scheme": 0, "auto_pick_theme": True,
}

# 仅在 config/ 整个丢失时用于自愈的最小兜底，正常运行不会用到
MINIMAL_THEME = {
    "label": "DAILY CARD · 今日份",
    "keywords": [],
    "colors": {
        "bg1": "#F2EDE3", "bg2": "#E3DACB", "card": "#FFFCF6",
        "ink": "#35342E", "sub": "#7D7A70", "accent": "#B08050",
        "accent2": "#7E9A88", "soft": "#E8DFCF", "pill": "#35342E",
        "pill_text": "#FFFCF6",
    },
    "motif": "circles",
    "stickers": ["sparkle", "leaf", "sun", "star"],
    "dark": False,
}


def _read_json(path, fallback=None):
    if not os.path.exists(path):
        return fallback
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    """原子写入，避免后台保存配置时把文件写坏。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cfg-", suffix=".json",
                               dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def ensure_config():
    """首次运行或配置被删掉时，从出厂模板重建可编辑配置。"""
    os.makedirs(config_dir(), exist_ok=True)
    if not os.path.exists(themes_file()):
        if os.path.exists(defaults_file()):
            shutil.copyfile(defaults_file(), themes_file())
        else:
            _write_json(themes_file(), {"version": 1, "default_theme": "quote",
                                        "themes": {"quote": MINIMAL_THEME}})
    if not os.path.exists(settings_file()):
        _write_json(settings_file(), DEFAULT_SETTINGS)
    if not os.path.exists(registry_file()):
        _write_json(registry_file(), {"version": 1, "groups": [], "motifs": [],
                                      "stickers": []})


def load_default_doc():
    doc = _read_json(defaults_file())
    if not doc:
        doc = _read_json(themes_file(), {"version": 1, "default_theme": "quote",
                                         "themes": {"quote": MINIMAL_THEME}})
    return doc


def load_doc():
    ensure_config()
    return _read_json(themes_file(), load_default_doc())


def default_theme_id():
    return load_doc().get("default_theme", "quote")


def load_themes():
    """把配置文件的结构化主题拍平成渲染器需要的字段结构。"""
    doc = load_doc()
    themes = {}
    for key, t in doc.get("themes", {}).items():
        colors = dict(t.get("colors") or {})
        flat = {ck: colors.get(ck, MINIMAL_THEME["colors"][ck]) for ck in COLOR_KEYS}
        flat.update(
            label=t.get("label", key),
            keywords=list(t.get("keywords") or []),
            motif=t.get("motif", "circles"),
            stickers=list(t.get("stickers") or []),
            dark=bool(t.get("dark", False)),
        )
        themes[key] = flat
    return themes


HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def save_doc(doc):
    """校验并保存主题配置，返回 (ok, message)。"""
    if not isinstance(doc, dict) or not isinstance(doc.get("themes"), dict):
        return False, "配置格式错误：缺少 themes 对象"
    if not doc["themes"]:
        return False, "至少需要保留一个主题"
    valid_ids = {s["id"] for s in load_registry().get("stickers", [])}
    for key, t in doc["themes"].items():
        if not re.match(r"^[A-Za-z0-9_\-]+$", str(key)):
            return False, "主题 ID 只能包含字母、数字、- 和 _：%s" % key
        colors = t.get("colors")
        if not isinstance(colors, dict):
            return False, "主题 %s 缺少 colors" % key
        for ck in COLOR_KEYS:
            if ck not in colors or not HEX_RE.match(str(colors[ck])):
                return False, "主题 %s 的颜色 %s 必须是 #RRGGBB 格式" % (key, ck)
        if not isinstance(t.get("stickers"), list) or not t["stickers"]:
            return False, "主题 %s 至少需要一个贴纸" % key
        if valid_ids:
            unknown = [s for s in t["stickers"] if s not in valid_ids]
            if unknown:
                return False, "主题 %s 含未知贴纸：%s" % (key, ", ".join(unknown))
        if not isinstance(t.get("keywords", []), list):
            return False, "主题 %s 的 keywords 必须是数组" % key
    doc["version"] = 1
    _write_json(themes_file(), doc)
    return True, "已保存 %d 套主题" % len(doc["themes"])


def reset_themes():
    doc = load_default_doc()
    _write_json(themes_file(), doc)
    return True, "已恢复出厂主题（%d 套）" % len(doc.get("themes", {}))


def load_settings():
    ensure_config()
    s = dict(DEFAULT_SETTINGS)
    s.update(_read_json(settings_file(), {}) or {})
    return s


def save_settings(patch):
    if not isinstance(patch, dict):
        return False, "设置必须是对象"
    s = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in patch:
            s[k] = patch[k]
    _write_json(settings_file(), s)
    return True, "设置已保存"


def load_registry():
    ensure_config()
    return _read_json(registry_file(), {"version": 1, "groups": [],
                                        "motifs": [], "stickers": []})


# ---------------------------------------------------------------------------
# 颜色工具 & 背景图配色方案
# ---------------------------------------------------------------------------

def hx(s):
    s = str(s).lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb[:3])


def hls_rgb(h, l, s):
    return tuple(v * 255 for v in colorsys.hls_to_rgb(
        h % 1.0, max(0, min(1, l)), max(0, min(1, s))))


def hls_of(color):
    r, g, b = (v / 255 for v in hx(color))
    return colorsys.rgb_to_hls(r, g, b)


def derive_palette(base, dark=False):
    """由单个主色派生一整套协调配色（背景/文字/强调/卡片/标签/贴纸共用）。"""
    h, _l, s = hls_of(base)
    accent = to_hex(hls_rgb(h, 0.66 if dark else 0.46, min(0.9, s * 1.3 + 0.24)))
    accent2 = to_hex(hls_rgb(h + 0.10, 0.72 if dark else 0.58,
                             min(0.85, s * 1.1 + 0.2)))
    soft = to_hex(hls_rgb(h, 0.30 if dark else 0.86, 0.30))
    return {
        "bg1": soft, "bg2": base,
        "card": "#222A31" if dark else "#FFFCF6",
        "ink": "#F8F5EE" if dark else "#252E2C",
        "sub": "#B9C0C6" if dark else "#6D7570",
        "accent": accent, "accent2": accent2, "soft": soft,
        "pill": accent,
        "pill_text": "#1B2229" if dark else "#FFFFFF",
    }


def compose_theme(colors, template, dark=None):
    """配色来自背景图 / 自定义主色，贴纸与标签仍取自标题主题。"""
    t = dict(colors)
    t["label"] = template.get("label", "DAILY CARD · 今日份")
    t["stickers"] = list(template.get("stickers") or ["sparkle", "star"])
    t["motif"] = template.get("motif", "circles")
    t["keywords"] = []
    t["dark"] = bool(template.get("dark", False) if dark is None else dark)
    return t


def hue_name(h, s, l):
    if s < 0.12:
        return "浅灰" if l > 0.6 else "深灰"
    if l < 0.22:
        return "深墨"
    if l > 0.84:
        return "浅白"
    deg = (h * 360) % 360
    table = [(15, "红"), (42, "橙"), (68, "黄"), (160, "绿"),
             (195, "青"), (255, "蓝"), (290, "紫"), (335, "粉"), (361, "红")]
    name = "红"
    for edge, label in table:
        if deg < edge:
            name = label
            break
    if l < 0.36:
        return "深" + name
    if l > 0.70:
        return "浅" + name
    return name


def _hue_dist(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def extract_schemes(path, n=4):
    """从背景图提取最多 n 套色相有区分度的候选配色方案。

    返回 [{id, name, base, dark, ratio, colors}, ...]，
    前端展示为可点击色卡，选中哪套就用哪套渲染。
    """
    im = Image.open(path).convert("RGB")
    small = im.copy()
    small.thumbnail((160, 160))
    px = small.load()
    pixels = [px[x, y] for y in range(small.height) for x in range(small.width)]

    buckets = {}
    total = 0
    avg = 0.0
    for r, g, b in pixels:
        avg += (r + g + b) / 3
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 14 or not (0.18 < mx / 255 < 0.96):
            continue
        key = (r // 26, g // 26, b // 26)
        acc = buckets.setdefault(key, [0, 0, 0, 0])
        acc[0] += r; acc[1] += g; acc[2] += b; acc[3] += 1
        total += 1
    avg = avg / max(1, len(pixels)) / 255
    dark = avg < 0.48

    ranked = sorted(buckets.values(), key=lambda a: a[3], reverse=True)
    bases, seen = [], []
    for r, g, b, cnt in ranked:
        base = to_hex((r / cnt, g / cnt, b / cnt))
        h, l, s = hls_of(base)
        # 色相过于接近的桶合并，保证候选方案彼此有区分度
        if any(_hue_dist(h, ph) < 0.055 and abs(l - pl) < 0.16
               for ph, pl in seen):
            continue
        seen.append((h, l))
        bases.append((base, cnt, h, s, l))
        if len(bases) >= n:
            break
    if not bases:
        bases = [("#6E8E9B", 0, 0.55, 0.3, 0.5)]

    schemes = []
    for i, (base, cnt, h, s, l) in enumerate(bases):
        schemes.append({
            "id": i,
            "name": ("主色" if i == 0 else "辅色 %d" % i) + " · " + hue_name(h, s, l),
            "base": base,
            "dark": dark,
            "ratio": round(cnt / total, 3) if total else 0,
            "colors": derive_palette(base, dark),
        })
    return schemes


def scheme_from_base(base, dark=False, name="自定义主色"):
    if not HEX_RE.match(str(base)):
        raise ValueError("主色必须是 #RRGGBB 格式")
    return {"id": -1, "name": name, "base": base, "dark": bool(dark),
            "ratio": 0, "colors": derive_palette(base, dark)}
