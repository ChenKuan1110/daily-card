#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日一句 / 打卡风格社交卡片生成器  (daily-card)

输入：一个标题 + 一个副标题
输出：一张可直接发朋友圈 / 公众号 / 小红书的 PNG 图片
      自动包含当天日期、与文案主题相关的插画贴纸、成套统一的色调。

特性
  * 纯本地渲染，不需要联网、不需要 AI 接口，中文文字 100% 可控、结果可复现
  * 关键词自动识别主题（学习打卡 / 早安 / 晚安 / 咖啡 / 运动 / 旅行 / 心情 / 工作 / 科技 / 节日 …）
    每个主题自带一整套配色 + 一组相关贴纸，贴纸与背景共用同一套色板 => 色调必然统一
  * 主题 / 配色 / 贴纸全部外置为 config/*.json，网页后台可视化编辑，脚本运行时读取
  * --bg-image 传入自己的照片/AI 生图：自动提取多套候选配色方案，任选一套或自定义主色
  * 多平台尺寸预设、可复现随机种子、自定义品牌落款

快速开始
  pip install Pillow
  python3 cardgen.py "今天也要好好生活" "把普通的日子过得响亮一点"
  python3 cardgen.py -t "Day 42 · 背完 100 个单词" -s "坚持比天赋更靠近答案" --platform xhs
  python3 cardgen.py -t "早安" -s "先起床，再谈梦想" --platform moments --theme morning
  python3 cardgen.py -t "山不见我" -s "周末出走计划" --bg-image ~/Pictures/bg.jpg --bg-scheme 2
  python3 cardgen.py --bg-image ~/Pictures/bg.jpg --list-schemes
  python3 server.py               # 启动网页后台 http://127.0.0.1:8777
  python3 cardgen.py --list-themes
  python3 cardgen.py            # 无参数进入交互式问答

配置文件（config/）
  themes.default.json  出厂主题模板，用于「恢复默认」
  themes.json          实际读取的主题配置（后台保存后即时生效）
  stickers.json        贴纸与背景纹样注册表
  settings.json        默认平台 / 落款 / 超采样 / 颗粒度 / 输出目录

参数说明
  -t/--title  -s/--subtitle      标题 / 副标题
  --date YYYY-MM-DD              指定日期（默认今天）
  --platform xhs|moments|wechat|story|wechat2
  --theme 主题名 / auto          强制主题，默认从标题+副标题推断
  --bg-image PATH                自定义背景图（自动取色）
  --bg-scheme N | #RRGGBB        选用第 N 套图片配色，或直接指定主色
  --list-schemes                 输出背景图的候选配色方案 JSON（配合 --bg-image）
  --config-dir PATH              使用另一套配置目录
  --init-config                  从出厂模板重建 themes.json
  --brand TEXT                   底部落款，如 "Claw · 每日一句"
  --out PATH                     输出路径
  --seed INT                     贴纸布局随机种子（同种子同构图）
  --font / --font-bold PATH      自定义中文字体
  --list-themes                  列出全部主题
"""

from __future__ import annotations

import argparse
import colorsys
import datetime as dt
import math
import os
import random
import re
import sys

import cardconfig as cfg

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
except ImportError:
    sys.exit("缺少依赖，请先运行：  pip install Pillow")


# ---------------------------------------------------------------------------
# 颜色工具
# ---------------------------------------------------------------------------

def hx(s):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb[:3])


def rgba(s, a=255):
    return hx(s) + (a,)


def mix(c1, c2, t):
    a, b = hx(c1), hx(c2)
    return to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def hls_rgb(h, l, s):
    return tuple(v * 255 for v in colorsys.hls_to_rgb(h % 1.0, max(0, min(1, l)), max(0, min(1, s))))


def shift_hue(color, delta, l=None, s=None):
    r, g, b = (v / 255 for v in hx(color))
    h, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return to_hex(hls_rgb(h + delta, ll if l is None else l, ss if s is None else s))


def luminance(color):
    r, g, b = (v / 255 for v in hx(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# 主题：全部来自 config/themes.json（网页后台可编辑），这里只负责加载与匹配
# 所有可见元素都只从当前主题色板取色，因此画面与贴纸的色调天然一致
# ---------------------------------------------------------------------------

def pick_theme(text, forced="auto", themes=None, default_theme="quote"):
    themes = themes if themes is not None else cfg.load_themes()
    if forced and forced != "auto":
        if forced not in themes:
            raise SystemExit("未知主题：%s（用 --list-themes 查看）" % forced)
        return forced
    low = text.lower()
    best = default_theme if default_theme in themes else next(iter(themes))
    score = 0
    for key, t in themes.items():
        n = sum(1 for kw in t["keywords"] if kw.lower() in low)
        # 长关键词权重更高
        n += sum(1 for kw in t["keywords"] if len(kw) >= 4 and kw.lower() in low)
        if n > score:
            best, score = key, n
    return best


def colors_for_bg(bg_image, scheme, template, dark_override=None):
    """配色来自背景图（或自定义主色），贴纸与标签仍取自标题主题。

    scheme 可以是候选方案序号，也可以是 #RRGGBB 自定义主色。
    dark_override 允许手动指定深色/浅色卡片。
    返回 (完整主题 dict, 全部候选方案列表)。
    """
    schemes = cfg.extract_schemes(bg_image)
    if isinstance(scheme, str) and scheme.startswith("#"):
        picked = cfg.scheme_from_base(scheme, schemes[0]["dark"] if schemes else False)
    else:
        idx = int(scheme or 0)
        picked = (schemes[idx % len(schemes)] if schemes
                  else cfg.scheme_from_base("#6E8E9B"))
    dark = picked["dark"] if dark_override is None else bool(dark_override)
    colors = (cfg.derive_palette(picked["base"], dark) if dark != picked["dark"]
              else picked["colors"])
    return cfg.compose_theme(colors, template, dark), schemes


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------

FONT_CANDIDATES = [
    ("Hiragino Sans GB.ttc", 2, "Hiragino Sans GB.ttc", 0),
    ("PingFang.ttc", 3, "PingFang.ttc", 0),
    ("STHeiti Medium.ttc", 1, "Hiragino Sans GB.ttc", 0),
    ("NotoSansCJK-Bold.ttc", 0, "NotoSansCJK-Regular.ttc", 0),
    ("msyhbd.ttc", 0, "msyh.ttc", 0),
]
FONT_DIRS = [
    "/System/Library/Fonts/", "/System/Library/Fonts/Supplemental/",
    "/Library/Fonts/", os.path.expanduser("~/Library/Fonts/"),
    "/usr/share/fonts/", "/usr/share/fonts/opentype/noto/",
    "C:/Windows/Fonts/",
]
LATIN_CANDIDATES = ["Montserrat-Medium.ttf", "Avenir Next.ttc", "Helvetica.ttc",
                    "DejaVuSans.ttf", "Arial.ttf"]


def find_fonts(bold_path=None, reg_path=None):
    def locate(name):
        if name and os.path.isabs(name) and os.path.exists(name):
            return name
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        return None

    if bold_path and reg_path:
        return (bold_path, 0, reg_path, 0)
    for b, bi, r, ri in FONT_CANDIDATES:
        pb, pr = locate(b), locate(r)
        if pb and pr:
            return (bold_path or pb, bi, reg_path or pr, ri)
    for b, bi, r, ri in FONT_CANDIDATES:
        pb = locate(b)
        if pb:
            return (pb, bi, pb, 0)
    sys.exit("找不到中文字体，请用 --font / --font-bold 指定一个 .ttf/.ttc 字体文件")


def find_latin():
    for name in LATIN_CANDIDATES:
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return (p, 1 if name == "Avenir Next.ttc" else 0)
    return None


def font_at(spec, size, index=0):
    return ImageFont.truetype(spec, max(8, int(size)), index=index)


# ---------------------------------------------------------------------------
# 文本排版
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"\s+|[A-Za-z0-9@#&'._%+\-/]+|[\u4e00-\u9fff\u3400-\u4dbf]|[^\s]")
NO_LINE_START = "，。！？、；：）】》”’…·,.;:!?)]}%"


def tokenize(text):
    return TOKEN_RE.findall(text)


def wrap_text(text, font, max_w):
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        for tok in tokenize(para):
            if tok.isspace():
                if cur:
                    cur += tok          # 保留英文单词之间的空格
                continue
            trial = cur + tok
            if not cur or font.getlength(trial) <= max_w:
                cur = trial
            elif tok in NO_LINE_START and font.getlength(trial) <= max_w * 1.10:
                cur = trial
            else:
                lines.append(cur.rstrip())
                cur = tok
        lines.append(cur.rstrip())
    return lines


def rebalance(lines, font, max_w):
    """兜底：避免标题最后一行只剩一两个字（孤行），从上一行借几个字过来。"""
    if len(lines) < 2:
        return lines
    last = lines[-1]
    if not last or font.getlength(last) >= max_w * 0.30:
        return lines
    toks = [t for t in tokenize(lines[-2]) if not t.isspace()]
    moved = []
    while toks and font.getlength("".join(moved) + last) < max_w * 0.34:
        moved.insert(0, toks.pop())
    if toks and moved and font.getlength("".join(toks)) > max_w * 0.40:
        lines[-2] = "".join(toks)
        lines[-1] = "".join(moved) + last
    return lines


def text(draw, xy, s, font, fill, anchor="lt"):
    draw.text(xy, s, font=font, fill=fill, anchor=anchor)


# ---------------------------------------------------------------------------
# 贴纸：局部坐标统一为 0~100，全部颜色来自当前主题色板
# ---------------------------------------------------------------------------

class Pen:
    def __init__(self, size):
        self.im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)
        self.k = size / 100.0

    def _box(self, b):
        return tuple(v * self.k for v in b)

    def _pts(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def ellipse(self, b, fill=None, outline=None, w=2):
        self.d.ellipse(self._box(b), fill=fill, outline=outline,
                       width=max(1, int(w * self.k)))

    def rrect(self, b, r, fill=None, outline=None, w=2):
        self.d.rounded_rectangle(self._box(b), radius=r * self.k, fill=fill,
                                 outline=outline, width=max(1, int(w * self.k)))

    def poly(self, pts, fill=None, outline=None, w=2):
        self.d.polygon(self._pts(pts), fill=fill)
        if outline:
            self.d.line(self._pts(pts + [pts[0]]), fill=outline,
                        width=max(1, int(w * self.k)), joint="curve")

    def line(self, pts, fill, w=3, joint="curve"):
        self.d.line(self._pts(pts), fill=fill, width=max(1, int(w * self.k)), joint=joint)

    def arc(self, b, start, end, fill, w=3):
        self.d.arc(self._box(b), start, end, fill=fill, width=max(1, int(w * self.k)))


def rot(cx, cy, x, y, deg):
    a = math.radians(deg)
    return (cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
            cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a))


def s_sun(p, C):
    a, b = C["accent"], C["accent2"]
    for i in range(8):
        ang = i * 45
        x1, y1 = rot(50, 50, 50, 14, ang)
        x2, y2 = rot(50, 50, 50, 4, ang)
        p.line([(x1, y1), (x2, y2)], a, 5)
    p.ellipse((25, 25, 75, 75), fill=a)
    p.ellipse((34, 32, 62, 60), fill=b)


def s_cloud(p, C):
    edge = rgba(C["accent2"], 120)          # 淡色底边，避免白云在浅背景上糊成一片
    body = C["card"]
    for dy in (4, 0):
        col = edge if dy else body
        p.ellipse((14, 42 + dy, 52, 80 + dy), fill=col)
        p.ellipse((36, 24 + dy, 80, 76 + dy), fill=col)
        p.rrect((20, 56 + dy, 84, 80 + dy), 12, fill=col)
    p.line([(30, 82), (74, 82)], C["soft"], 4)


def s_moon(p, C):
    p.ellipse((12, 10, 88, 86), fill=C["accent"])
    p.ellipse((38, 4, 96, 62), fill=(0, 0, 0, 0))
    p.ellipse((68, 66, 78, 76), fill=C["accent2"])
    p.ellipse((82, 40, 90, 48), fill=C["accent2"])


def s_star(p, C):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = 46 if i % 2 == 0 else 19
        pts.append((50 + r * math.cos(ang), 50 + r * math.sin(ang)))
    p.poly(pts, fill=C["accent2"])


def s_sparkle(p, C):
    p.poly([(50, 4), (58, 42), (96, 50), (58, 58), (50, 96),
            (42, 58), (4, 50), (42, 42)], fill=C["accent"])
    p.ellipse((46, 46, 54, 54), fill=C["card"])


def s_leaf(p, C):
    up, dn = [], []
    for i in range(25):
        t = i / 24
        x = 12 + 76 * t
        o = 16 * math.sin(math.pi * t)
        up.append((x, 88 - 76 * t - o))
        dn.append((x, 88 - 76 * t + o))
    p.poly(up + dn[::-1], fill=C["accent2"])
    p.line([(14, 86), (86, 14)], C["card"], 2.5)
    for t in (0.32, 0.52, 0.70):
        x, y = 12 + 76 * t, 88 - 76 * t
        p.line([(x, y), (x + 12, y - 4)], C["card"], 2)


def s_flower(p, C):
    for i in range(5):
        a = i * 72
        petal = [rot(50, 50, 50 + 12 * math.cos(math.radians(t)),
                     28 + 12 * math.sin(math.radians(t)), a) for t in range(0, 360, 30)]
        p.poly(petal, fill=C["accent"])
    p.ellipse((39, 39, 61, 61), fill=C["accent2"])
    p.ellipse((46, 46, 54, 54), fill=C["card"])


def s_heart(p, C):
    pts = []
    for i in range(49):
        t = 2 * math.pi * i / 48
        x = 50 + 43 * (16 * math.sin(t) ** 3) / 17
        y = 50 - 43 * (13 * math.cos(t) - 5 * math.cos(2 * t)
                       - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17
        pts.append((x, y + 4))
    p.poly(pts, fill=C["accent"])
    p.ellipse((30, 28, 39, 37), fill=C["card"])


def s_book(p, C):
    p.poly([(6, 32), (47, 24), (47, 80), (6, 88)], fill=C["card"], outline=C["ink"], w=2)
    p.poly([(53, 24), (94, 32), (94, 88), (53, 80)], fill=C["card"], outline=C["ink"], w=2)
    p.line([(50, 24), (50, 80)], C["ink"], 3)
    for i in range(3):
        y = 42 + i * 11
        p.line([(14, y), (39, y - 4)], C["soft"], 2.5)
        p.line([(61, y - 4), (86, y)], C["soft"], 2.5)
    p.rrect((76, 66, 92, 86), 2, fill=C["accent"])


def s_pencil(p, C):
    p.poly([(38, 8), (62, 8), (62, 70), (50, 88), (38, 70)], fill=C["accent2"])
    p.rrect((38, 4, 62, 16), 2, fill=C["soft"])
    p.poly([(50, 88), (38, 70), (62, 70)], fill=C["card"])
    p.poly([(45, 78), (50, 88), (55, 78)], fill=C["ink"])
    p.line([(38, 24), (62, 24)], C["card"], 2)


def s_coffee(p, C):
    p.arc((66, 30, 96, 66), 280, 80, C["accent2"], 6)
    p.poly([(18, 38), (70, 38), (64, 82), (24, 82)], fill=C["card"],
           outline=C["ink"], w=2)
    p.rrect((16, 34, 72, 43), 4, fill=C["accent"])
    p.ellipse((26, 39, 62, 44), fill=C["ink"])
    for x in (34, 46, 58):
        p.line([(x, 26), (x - 4, 20), (x + 1, 13), (x - 2, 7)], C["accent2"], 2.5)
    p.rrect((12, 82, 78, 88), 2, fill=C["accent2"])


def s_bulb(p, C):
    p.ellipse((22, 8, 78, 64), fill=C["accent2"])
    p.poly([(34, 54), (66, 54), (62, 76), (38, 76)], fill=C["card"])
    p.rrect((37, 76, 63, 84), 3, fill=C["ink"])
    p.rrect((39, 86, 61, 92), 2, fill=C["accent"])
    p.line([(50, 24), (50, 48)], C["card"], 3)
    p.line([(40, 36), (60, 36)], C["card"], 3)
    for ang in (0, 45, 135, 180, 225, 315):
        a, b = rot(50, 36, 50, 0, ang)
        c, d = rot(50, 36, 50, -6, ang)
        p.line([(a, b), (c, d)], C["accent"], 3)


def s_clock(p, C):
    p.ellipse((10, 10, 90, 90), fill=C["card"], outline=C["accent"], w=5)
    p.ellipse((15, 15, 85, 85), outline=C["soft"], w=2)
    for i in range(12):
        x1, y1 = rot(50, 50, 50, 20, i * 30)
        x2, y2 = rot(50, 50, 50, 25, i * 30)
        p.line([(x1, y1), (x2, y2)], C["accent2"], 2)
    p.line([(50, 50), (50, 30)], C["ink"], 4)
    p.line([(50, 50), (67, 58)], C["ink"], 4)
    p.ellipse((46, 46, 54, 54), fill=C["accent"])


def s_calendar(p, C):
    p.rrect((10, 20, 90, 90), 10, fill=C["card"], outline=C["ink"], w=2)
    p.rrect((10, 20, 90, 38), 9, fill=C["accent"])
    p.rrect((24, 12, 32, 30), 3, fill=C["ink"])
    p.rrect((68, 12, 76, 30), 3, fill=C["ink"])
    for r in range(3):
        for c in range(4):
            p.ellipse((20 + c * 17, 46 + r * 14, 26 + c * 17, 52 + r * 14),
                      fill=C["soft"])
    p.ellipse((54, 60, 70, 76), fill=C["accent2"])


def s_check(p, C):
    p.rrect((8, 8, 92, 92), 18, fill=C["accent"])
    p.line([(26, 52), (44, 70), (76, 32)], C["card"], 9)


def s_dumbbell(p, C):
    p.rrect((28, 44, 72, 56), 3, fill=C["ink"])
    p.rrect((14, 28, 26, 72), 4, fill=C["accent"])
    p.rrect((74, 28, 86, 72), 4, fill=C["accent"])
    p.rrect((6, 36, 14, 64), 3, fill=C["accent2"])
    p.rrect((86, 36, 94, 64), 3, fill=C["accent2"])


def s_bolt(p, C):
    p.poly([(56, 4), (22, 56), (46, 56), (38, 96), (80, 40), (54, 40), (68, 4)],
           fill=C["accent2"])


def s_mountain(p, C):
    p.ellipse((66, 14, 86, 34), fill=C["accent2"])
    p.poly([(4, 82), (38, 24), (72, 82)], fill=C["accent"])
    p.poly([(38, 24), (26, 44), (34, 42), (42, 50), (50, 44)], fill=C["card"])
    p.poly([(46, 82), (74, 38), (98, 82)], fill=C["accent2"])
    p.line([(2, 84), (98, 84)], C["ink"], 3)


def s_wave(p, C):
    for i, col in enumerate((C["soft"], C["accent2"], C["accent"])):
        pts = [(x, 46 + i * 15 + 5 * math.sin(x / 11 + i)) for x in range(0, 101, 4)]
        p.poly(pts + [(100, 100), (0, 100)], fill=col)


def s_plane(p, C):
    p.poly([(4, 46), (94, 12), (60, 90), (46, 58)], fill=C["card"],
           outline=C["ink"], w=2)
    p.poly([(46, 58), (94, 12), (56, 60)], fill=C["accent"])
    p.line([(4, 46), (46, 58)], C["accent2"], 2)


def s_balloon(p, C):
    p.ellipse((18, 4, 82, 74), fill=C["accent"])
    p.poly([(46, 72), (54, 72), (50, 82)], fill=C["accent"])
    p.line([(50, 82), (46, 90), (54, 96), (48, 100)], C["ink"], 2)
    p.ellipse((32, 16, 46, 36), fill=C["card"])


def s_camera(p, C):
    p.rrect((6, 30, 94, 86), 10, fill=C["ink"])
    p.rrect((28, 22, 52, 34), 4, fill=C["ink"])
    p.ellipse((34, 40, 66, 72), fill=C["card"], outline=C["accent"], w=5)
    p.ellipse((43, 49, 57, 63), fill=C["accent2"])
    p.ellipse((76, 40, 86, 50), fill=C["accent"])


def s_note(p, C):
    p.ellipse((10, 62, 38, 84), fill=C["accent"])
    p.ellipse((52, 54, 80, 76), fill=C["accent"])
    p.line([(36, 66), (36, 12), (78, 12), (78, 58)], C["ink"], 5)
    p.poly([(78, 12), (94, 26), (78, 36)], fill=C["accent2"])


def s_cat(p, C):
    p.poly([(18, 38), (24, 8), (44, 28)], fill=C["accent2"])
    p.poly([(82, 38), (76, 8), (56, 28)], fill=C["accent2"])
    p.ellipse((16, 24, 84, 88), fill=C["card"])
    p.ellipse((30, 46, 38, 56), fill=C["ink"])
    p.ellipse((62, 46, 70, 56), fill=C["ink"])
    p.poly([(46, 62), (54, 62), (50, 68)], fill=C["accent"])
    for y in (62, 70):
        p.line([(18, y), (34, y + 3)], C["ink"], 1.6)
        p.line([(82, y), (66, y + 3)], C["ink"], 1.6)


def s_quote(p, C):
    for x in (16, 56):
        p.ellipse((x, 10, x + 34, 50), fill=C["accent"])
        p.poly([(x, 38), (x + 34, 38), (x + 4, 88), (x - 4, 62)], fill=C["accent"])


def s_stamp(p, C):
    p.ellipse((6, 6, 94, 94), outline=C["accent"], w=6)
    p.ellipse((14, 14, 86, 86), outline=C["accent"], w=2)
    p.line([(28, 52), (44, 68), (74, 34)], C["accent"], 8)


def s_grid(p, C):
    for r in range(4):
        for c in range(4):
            p.rrect((6 + c * 24, 6 + r * 24, 22 + c * 24, 22 + r * 24), 4,
                    fill=C["accent2"] if (r + c) % 3 else C["accent"])


def s_bird(p, C):
    p.line([(8, 62), (34, 40), (58, 60), (88, 34)], C["accent"], 5)
    p.ellipse((30, 38, 38, 46), fill=C["accent2"])


STICKERS = {k[2:]: v for k, v in list(globals().items()) if k.startswith("s_")}


def make_sticker(kind, size, C, angle=0, alpha=255):
    fn = STICKERS.get(kind)
    if fn is None:
        kind = "sparkle"
        fn = STICKERS[kind]
    p = Pen(size)
    fn(p, C)
    im = p.im
    if angle:
        im = im.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 255:
        a = im.getchannel("A").point(lambda v: v * alpha // 255)
        im.putalpha(a)
    return im


def paste_sticker(canvas, st, cx, cy):
    w, h = st.size
    x, y = int(cx - w / 2), int(cy - h / 2)
    # 裁掉画布外的部分，避免 alpha_composite 越界
    sx = sy = 0
    if x < 0:
        sx, w, x = -x, w + x, 0
    if y < 0:
        sy, h, y = -y, h + y, 0
    if x + w > canvas.width:
        w = canvas.width - x
    if y + h > canvas.height:
        h = canvas.height - y
    if w <= 0 or h <= 0 or sx < 0 or sy < 0:
        return
    piece = st.crop((sx, sy, sx + w, sy + h))
    canvas.alpha_composite(piece, (x, y))


# ---------------------------------------------------------------------------
# 背景：渐变 + 光晕 + 主题纹样 + 纸张颗粒
# ---------------------------------------------------------------------------

def gradient(W, H, c1, c2):
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    a, b = hx(c1), hx(c2)
    for y in range(H):
        t = y / max(1, H - 1)
        # 轻微 S 曲线让渐变更柔和
        t = t * t * (3 - 2 * t)
        d.line([(0, y), (W, y)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return im.convert("RGBA")


def draw_motif(canvas, C, motif, rng, S):
    W, H = canvas.size
    d = ImageDraw.Draw(canvas, "RGBA")
    a1 = rgba(C["accent"], 26)
    a2 = rgba(C["accent2"], 24)
    soft = rgba(C["soft"], 150)
    if motif == "circles":
        for _ in range(5):
            r = rng.randint(int(150 * S), int(360 * S))
            x, y = rng.randint(-r // 2, W), rng.randint(-r // 2, H)
            d.ellipse((x - r, y - r, x + r, y + r), fill=soft)
        d.arc((-W * 0.35, H * 0.55, W * 0.55, H * 1.25), 180, 350, fill=a1, width=int(40 * S))
    elif motif == "dots":
        step = int(46 * S)
        for y in range(step, H, step):
            for x in range(step, W, step):
                if (x // step + y // step) % 3 == 0:
                    r = 3 * S
                    d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(C["accent"], 60))
    elif motif == "grid":
        step = int(64 * S)
        for x in range(0, W + step, step):
            d.line([(x, 0), (x, H)], fill=rgba(C["accent"], 13), width=max(1, int(S)))
        for y in range(0, H + step, step):
            d.line([(0, y), (W, y)], fill=rgba(C["accent"], 13), width=max(1, int(S)))
        d.ellipse((W * 0.72, -H * 0.12, W * 1.28, H * 0.34), fill=soft)
    elif motif == "rays":
        cx, cy = W * 0.82, H * 0.08
        for i in range(9):
            ang = math.radians(150 + i * 14)
            x2, y2 = cx + math.cos(ang) * W * 1.4, cy + math.sin(ang) * H * 1.4
            d.line([(cx, cy), (x2, y2)], fill=rgba(C["accent2"], 16), width=int(46 * S))
    elif motif == "waves":
        for i in range(3):
            pts = [(x, H * (0.74 + i * 0.09) + 26 * S * math.sin(x / (110 * S) + i))
                   for x in range(0, W + 20, max(4, int(16 * S)))]
            pts += [(W, H), (0, H)]
            d.polygon(pts, fill=rgba(C["accent2"] if i == 1 else C["soft"], 90))
    elif motif == "stars":
        for _ in range(46):
            x, y = rng.randint(0, W), rng.randint(0, H)
            r = rng.uniform(1.2, 3.4) * S
            d.ellipse((x - r, y - r, x + r, y + r), fill=rgba(C["accent2"], 130))
    # 四角柔和光晕
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    for (fx, fy, r, col) in ((0.05, 0.02, 0.55, C["accent2"]),
                             (0.98, 0.95, 0.60, C["accent"])):
        rr = r * W
        gd.ellipse((fx * W - rr, fy * H - rr, fx * W + rr, fy * H + rr),
                   fill=rgba(col, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(int(90 * S)))
    canvas.alpha_composite(glow)


def add_grain(canvas, S, strength=10):
    W, H = canvas.size
    n = Image.effect_noise((max(2, W // 4), max(2, H // 4)), 22).convert("L")
    n = n.resize((W, H), Image.BILINEAR)
    mask = n.point(lambda v: max(0, min(255, (v - 108) * strength // 22)))
    overlay = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    canvas.paste(Image.composite(overlay, canvas, mask))


def cover_bg(path, W, H):
    im = Image.open(path).convert("RGBA")
    sw, sh = im.size
    scale = max(W / sw, H / sh)
    im = im.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


# ---------------------------------------------------------------------------
# 主渲染
# ---------------------------------------------------------------------------

PLATFORMS = {
    "xhs":      (1080, 1440, "小红书 / 3:4 竖版"),
    "moments":  (1080, 1080, "朋友圈 / 1:1 方图"),
    "wechat":   (900,  500,  "公众号封面 / 横版"),
    "story":    (1080, 1920, "竖屏海报 / 9:16"),
    "wechat2":  (1080, 460,  "公众号首图 / 2.35:1"),
}

WEEK_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
WEEK_EN = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MONTH_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def render(title, subtitle, *, date=None, platform="xhs", theme_name="auto",
           bg_image=None, brand="", out=None, seed=None,
           bold_spec=None, reg_spec=None, themes=None, settings=None,
           bg_scheme=0, dark_override=None):
    if platform not in PLATFORMS:
        raise SystemExit("未知平台：%s（可选 %s）" % (platform, "/".join(PLATFORMS)))
    themes = themes if themes is not None else cfg.load_themes()
    settings = settings if settings is not None else cfg.load_settings()
    if theme_name == "auto":
        theme_name = pick_theme(title + " " + subtitle, "auto", themes,
                                cfg.default_theme_id())
    if theme_name not in themes:
        raise SystemExit("未知主题：%s（用 --list-themes 查看）" % theme_name)
    W0, H0, _ = PLATFORMS[platform]
    today = date or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)

    SS = max(1, int(settings.get("supersample", 2)))   # 超采样，最后 LANCZOS 缩小
    W, H = W0 * SS, H0 * SS
    S = min(W / 1080, H / 800)             # 统一比例因子，横版自动缩小字号

    if bg_image:
        # 配色来自背景图（选中的方案 / 自定义主色），贴纸与标签仍取自标题主题
        C, _schemes = colors_for_bg(bg_image, bg_scheme, themes[theme_name],
                                    dark_override)
        canvas = cover_bg(bg_image, W, H)
        veil = Image.new("RGBA", (W, H), rgba("#101820" if C["dark"] else "#FFF9EE",
                                              96 if C["dark"] else 74))
        canvas = Image.alpha_composite(canvas, veil)
        canvas = canvas.filter(ImageFilter.GaussianBlur(int(1.2 * S)))
    else:
        C = dict(themes[theme_name])
        canvas = gradient(W, H, C["bg1"], C["bg2"])
        draw_motif(canvas, C, C["motif"], random.Random(seed or 7), S)

    rng = random.Random((seed if seed is not None else 20261111) + W0)
    accent, accent2 = C["accent"], C["accent2"]
    ink, sub, card = C["ink"], C["sub"], C["card"]
    dark = C["dark"]

    # --- 背景层贴纸（卡片下方，围绕四周漂浮） ---
    anchors = [(0.11, 0.10, 0.17), (0.62, 0.06, 0.12), (0.06, 0.52, 0.11),
               (0.94, 0.58, 0.16), (0.13, 0.90, 0.14), (0.85, 0.91, 0.13)]
    kinds = C["stickers"]
    for i, (fx, fy, fr) in enumerate(anchors):
        kind = kinds[i % len(kinds)]
        size = int(min(W, H) * fr * rng.uniform(0.82, 1.18))
        st = make_sticker(kind, size, C, angle=rng.randint(-22, 22), alpha=225)
        paste_sticker(canvas, st, fx * W, fy * H)

    # --- 字体 ---
    bp, bi, rp, ri = find_fonts(bold_spec, reg_spec)
    latin = find_latin()
    lp = latin[0] if latin else rp
    li = latin[1] if latin else ri

    # --- 版式常量：横版空间紧，整体压缩间距；先算出「文字可用高度」再选字号 ---
    compact = H < W
    k = 0.55 if compact else 1.0
    margin = int(92 * S)
    card_w = W - 2 * margin
    pad = int(70 * S * (0.78 if compact else 1.0))
    inner_w = card_w - 2 * pad
    pill_h = int(48 * S)
    quote_h = 0 if compact else int(84 * S)
    gap1, gap2 = int(40 * S * k), int(34 * S * k)
    gap3, gap4 = int(26 * S * k), int(48 * S * k)
    divider_h, date_h = int(14 * S), int(40 * S)
    top_inset = int(26 * S)
    card_max_h = int(H * (0.80 if compact else 0.84))
    fixed_h = (pill_h + gap1 + quote_h + gap2 // 2 + gap2 + divider_h
               + gap3 + gap4 + date_h + top_inset)
    max_text_h = max(int(120 * S), card_max_h - 2 * pad - fixed_h)
    title_sizes = [112, 104, 96, 88, 80, 72, 64, 56, 48, 42]
    # 遍历所有可用字号，挑「行数少 + 各行长度均衡 + 字号够大」的最佳组合，
    # 避免机械换行出现「今 / 天背完」这类断句或最后只剩一个字。
    candidates = []
    for ts in title_sizes:
        tsize = int(ts * S)
        f_t = font_at(bp, tsize, bi)
        tl = wrap_text(title, f_t, inner_w)
        ssize = int(34 * S)
        f_s = font_at(rp, ssize, ri)
        sl = wrap_text(subtitle, f_s, inner_w * 0.94) if subtitle else []
        th = len(tl) * int(tsize * 1.38)
        sh = len(sl) * int(ssize * 1.72)
        if th + sh <= max_text_h and len(tl) <= 9:
            widths = [f_t.getlength(l) for l in tl if l] or [1]
            balance = 1 - (max(widths) - min(widths)) / inner_w
            fill = min(widths) / inner_w
            ideal_lines = 1 if compact else 2
            score = (-3.0 * len(tl) + 2.0 * balance + 1.5 * fill
                     + 4.0 * ts / 112 - (2.5 if ts < 80 else 0)
                     - 2.2 * abs(len(tl) - ideal_lines))
            candidates.append((score, tsize, f_t, tl, ssize, f_s, sl))
    if candidates:
        _, tsize, f_title, tlines, ssize, f_sub, slines = max(candidates, key=lambda c: c[0])
    else:                                   # 超长文案兜底：继续缩小直到装得下
        ssize = int(34 * S)
        f_sub = font_at(rp, ssize, ri)
        slines = wrap_text(subtitle, f_sub, inner_w * 0.94) if subtitle else []
        sub_h = len(slines) * int(ssize * 1.72)
        for ts in [42, 36, 30, 24, 20]:
            tsize = int(ts * S)
            f_title = font_at(bp, tsize, bi)
            tlines = wrap_text(title, f_title, inner_w)
            if len(tlines) * int(tsize * 1.38) + sub_h <= max_text_h:
                break
    tlines = rebalance(tlines, f_title, inner_w)
    line_h = int(tsize * 1.38)
    sub_line_h = int(ssize * 1.72)

    # --- 卡片尺寸（高度随文案自适应，不再硬截断，保证文字与日期严格对齐） ---
    content_h = (pill_h + gap1 + quote_h + gap2 // 2 + len(tlines) * line_h
                 + gap2 + divider_h + gap3 + len(slines) * sub_line_h
                 + gap4 + date_h)
    card_h = content_h + 2 * pad + top_inset
    cy0 = max(int(24 * S), int(H * 0.47 - card_h / 2))
    cx0 = margin
    cx1, cy1 = W - margin, cy0 + card_h
    radius = int(38 * S)

    # --- 卡片阴影 ---
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow, "RGBA")
    sd.rounded_rectangle((cx0, cy0 + int(16 * S), cx1, cy1 + int(16 * S)),
                         radius=radius, fill=(20, 24, 20, 74 if not dark else 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(30 * S)))
    canvas.alpha_composite(shadow)

    # --- 卡片本体 ---
    card_alpha = 236 if dark else 247
    d = ImageDraw.Draw(canvas, "RGBA")
    d.rounded_rectangle((cx0, cy0, cx1, cy1), radius=radius, fill=rgba(card, card_alpha))
    d.rounded_rectangle((cx0, cy0, cx1, cy1), radius=radius,
                        outline=rgba("#FFFFFF" if dark else ink, 34 if dark else 16),
                        width=max(1, int(2 * S)))
    # 卡片顶部一条主题色细带
    d.rounded_rectangle((cx0 + pad, cy0 + int(30 * S), cx0 + pad + int(64 * S),
                         cy0 + int(36 * S)), radius=int(3 * S), fill=rgba(accent, 255))

    x = cx0 + pad
    y = cy0 + pad + top_inset

    # --- 顶部胶囊标签 + DAY 计数 ---
    f_pill = font_at(rp, int(20 * S), ri)
    label = C["label"]
    pill_w = int(f_pill.getlength(label) + 34 * S)
    d.rounded_rectangle((x, y, x + pill_w, y + pill_h), radius=pill_h // 2,
                        fill=rgba(C["pill"], 255))
    text(d, (x + int(17 * S), y + pill_h / 2), label, f_pill,
         rgba(C["pill_text"], 255), anchor="lm")
    f_day = font_at(lp, int(19 * S), li)
    day_txt = "DAY %03d" % today.timetuple().tm_yday
    text(d, (cx1 - pad, y + pill_h / 2), day_txt, f_day, rgba(sub, 200), anchor="rm")
    y += pill_h + gap1

    # --- 引号装饰 + 右上角主题小贴纸 ---
    if quote_h:
        q = make_sticker("quote", int(80 * S), C, alpha=180 if dark else 135)
        paste_sticker(canvas, q, x + int(36 * S), y + int(32 * S))
    # 主题小贴纸贴在卡片右上角外侧，像真实贴纸一样压住边框，不遮挡 DAY 编号和标题
    corner = make_sticker(kinds[0], int(112 * S), C, angle=14, alpha=225)
    paste_sticker(canvas, corner, cx1 - int(4 * S), cy0 + int(30 * S))
    y += quote_h + gap2 // 2

    d = ImageDraw.Draw(canvas, "RGBA")
    # --- 标题 ---
    for ln in tlines:
        # 极淡描边让粗体更有质感
        d.text((x, y), ln, font=f_title, fill=rgba(ink, 255), anchor="lt",
               stroke_width=max(0, int(0.6 * S)), stroke_fill=rgba(ink, 255))
        y += line_h
    y += gap2

    # --- 分隔符 ---
    mid = x + int(46 * S)
    d.rounded_rectangle((x, y + int(6 * S), mid - int(12 * S), y + int(9 * S)),
                        radius=int(2 * S), fill=rgba(accent, 255))
    d.ellipse((mid - int(5 * S), y + int(2 * S), mid + int(5 * S), y + int(12 * S)),
              fill=rgba(accent2, 255))
    d.line([(mid + int(12 * S), y + int(7 * S)), (mid + int(96 * S), y + int(7 * S))],
           fill=rgba(accent, 90), width=max(1, int(2 * S)))
    y += divider_h + gap3

    # --- 副标题 ---
    for ln in slines:
        text(d, (x, y), ln, f_sub, rgba(sub, 255), anchor="lt")
        y += sub_line_h
    y += gap4

    # --- 日期行 ---
    date_y = cy1 - pad - date_h + int(4 * S)
    d.line([(x, date_y - int(20 * S)), (cx1 - pad, date_y - int(20 * S))],
           fill=rgba(ink, 26 if not dark else 50), width=max(1, int(1.5 * S)))
    f_date = font_at(lp, int(25 * S), li)
    f_date_sm = font_at(rp, int(19 * S), ri)
    date_main = "%04d . %02d . %02d" % (today.year, today.month, today.day)
    text(d, (x, date_y), date_main, f_date, rgba(ink, 230), anchor="lt")
    tail = "%s  %s" % (WEEK_EN[today.weekday()], WEEK_CN[today.weekday()])
    text(d, (cx1 - pad, date_y + int(3 * S)), tail, f_date_sm,
         rgba(sub, 235), anchor="rt")

    # --- 前景小贴纸（压在卡片边缘，增加层次） ---
    for (fx, fy, kind, size_f, ang) in (
        (0.90, 0.20, kinds[min(2, len(kinds) - 1)], 0.085, -18),
        (0.095, 0.815, kinds[0], 0.075, 16),
    ):
        st = make_sticker(kind, int(min(W, H) * size_f), C, angle=ang, alpha=245)
        paste_sticker(canvas, st, fx * W, fy * H)

    # --- 底部落款 / 日期角标 ---
    f_brand = font_at(rp, int(18 * S), ri)   # 用中文字体，避免落款里的中文变方块
    bottom = (brand.strip() + "   ·   " if brand.strip() else "")
    bottom += "%s %d, %d" % (MONTH_EN[today.month - 1], today.day, today.year)
    bottom_y = H - (int(34 * S) if H < W else int(60 * S))
    text(d, (W / 2, bottom_y), bottom, f_brand,
         rgba(ink if not dark else "#FFFFFF", 175), anchor="mt")

    # --- 颗粒 + 输出 ---
    add_grain(canvas, S, strength=int(settings.get("grain", 9)))
    final = canvas.convert("RGB").resize((W0, H0), Image.LANCZOS)
    if out is None:
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")[:18] or "card"
        out = os.path.join(cfg.output_dir(),
                           "%s-%s-%s.png" % (safe, today.isoformat(), platform))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    final.save(out, "PNG", optimize=True)
    return out, theme_name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def interactive():
    print("\n  🐾 每日一句 · 打卡卡片生成器\n")
    title = input("  标题（必填）: ").strip()
    while not title:
        title = input("  标题不能为空，再来一次: ").strip()
    subtitle = input("  副标题（可留空）: ").strip()
    print("  平台: 1 小红书3:4  2 朋友圈方图  3 公众号横图  4 竖屏9:16")
    pick = input("  选一个 [1]: ").strip() or "1"
    platform = {"1": "xhs", "2": "moments", "3": "wechat", "4": "story"}.get(pick, "xhs")
    theme_name = input("  主题（直接回车=自动识别）: ").strip() or "auto"
    brand = input("  落款（可留空）: ").strip()
    return title, subtitle, platform, theme_name, brand


def main():
    bootstrap = cfg.load_settings()
    ap = argparse.ArgumentParser(
        description="输入标题+副标题，输出一张含当天日期、主题贴纸的社交平台卡片图",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="依次作为标题、副标题")
    ap.add_argument("-t", "--title")
    ap.add_argument("-s", "--subtitle", default="")
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天")
    ap.add_argument("--platform", default=bootstrap.get("platform", "xhs"),
                    choices=list(PLATFORMS))
    ap.add_argument("--theme", default="auto")
    ap.add_argument("--bg-image", help="自定义背景图，自动提取主色统一色调")
    ap.add_argument("--bg-scheme", default=str(bootstrap.get("bg_scheme", 0)),
                    help="背景图配色方案序号（0/1/2/3），或 #RRGGBB 自定义主色")
    ap.add_argument("--brand", default=bootstrap.get("brand", ""))
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=bootstrap.get("seed"))
    ap.add_argument("--font", help="常规中文字体路径")
    ap.add_argument("--font-bold", help="粗体中文字体路径")
    ap.add_argument("--config-dir", help="指定配置目录（默认 ./config）")
    ap.add_argument("--init-config", action="store_true", help="从出厂模板重建配置")
    ap.add_argument("--list-themes", action="store_true")
    ap.add_argument("--list-schemes", action="store_true",
                    help="配合 --bg-image 输出候选配色方案 JSON")
    ap.add_argument("--interactive", action="store_true", help="交互式输入标题与副标题")
    args = ap.parse_args()

    if args.config_dir:
        cfg.set_config_dir(args.config_dir)
    cfg.ensure_config()
    if args.init_config:
        ok, msg = cfg.reset_themes()
        print("  %s %s" % ("✅" if ok else "❌", msg))
        return
    themes = cfg.load_themes()
    settings = cfg.load_settings()

    if args.list_themes:
        print("可用主题（来自 %s）：" % cfg.themes_file())
        for k, v in themes.items():
            print("  %-10s %-18s 贴纸: %s" % (k, v["label"], ", ".join(v["stickers"])))
        print("\n平台尺寸（--platform）：")
        for k, (w, h, desc) in PLATFORMS.items():
            print("  %-9s %d x %d   %s" % (k, w, h, desc))
        return

    if args.list_schemes:
        if not args.bg_image:
            ap.error("--list-schemes 需要同时传 --bg-image")
        import json
        print(json.dumps(cfg.extract_schemes(args.bg_image), ensure_ascii=False, indent=2))
        return

    if args.interactive or (not args.title and not args.words and sys.stdin.isatty()):
        t, s, p, th, br = interactive()
        args.title, args.subtitle, args.platform = t, s, p
        args.theme, args.brand = th, br

    title = args.title or (args.words[0] if args.words else None)
    subtitle = args.subtitle or (args.words[1] if len(args.words) > 1 else "")
    if not title:
        ap.error("请提供标题，例如：python3 cardgen.py \"标题\" \"副标题\"")

    theme_name = pick_theme(title + " " + subtitle, args.theme, themes,
                            cfg.default_theme_id())
    out, used = render(
        title, subtitle, date=args.date, platform=args.platform,
        theme_name=theme_name, bg_image=args.bg_image, brand=args.brand,
        out=args.out, seed=args.seed, bold_spec=args.font_bold, reg_spec=args.font,
        themes=themes, settings=settings, bg_scheme=args.bg_scheme)
    print("\n  ✅ 生成完成")
    print("     主题：%s  (%s)" % (used, themes[used]["label"]))
    print("     文件：%s\n" % out)


if __name__ == "__main__":
    main()
