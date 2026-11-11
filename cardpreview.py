#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主题草案可视化预览（未保存即可看到效果）

输入一份内存里的主题字典，输出四类反馈，全程不写 config/themes.json：

  1. card            真实卡片渲染（复用 cardgen.render，只是把主题换成草案）
  2. legend          语义化配色示意图：真实纹样背景 + 卡片层级 + 10 个颜色角色标注
  3. stickers        当前配色下的贴纸条
  4. sticker_sheet   当前配色下的全量贴纸 sprite（供前端图标网格切片显示）

另外提供 diagnose()：按 WCAG 对比度检查文字可读性、明暗设定与背景是否矛盾，
把「看起来有点怪」变成一句能照着改的中文提示。
"""

from __future__ import annotations

import base64
import io
import math
import os
import random
import re
import uuid

from PIL import Image, ImageDraw, ImageFilter

import cardconfig as cfg
import cardgen

DRAFT_ID = "__draft__"
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# (配置键, 中文角色, 作用说明) —— 顺序即语义图里的展示顺序
COLOR_ROLES = [
    ("bg1", "背景·上", "渐变起始，画面最上方"),
    ("bg2", "背景·下", "渐变结束，画面最下方"),
    ("card", "卡片底", "中央卡片，承托全部文字"),
    ("ink", "主文字", "标题颜色"),
    ("sub", "副文字", "副标题、日期与辅助信息"),
    ("accent", "强调色", "标签、纹样与贴纸主色"),
    ("accent2", "辅助色", "纹样与贴纸的第二层点缀"),
    ("soft", "柔和色", "大面积浅色块与柔光"),
    ("pill", "标签底", "卡片顶部的小标签"),
    ("pill_text", "标签字", "小标签上的文字"),
]

NEUTRAL_INK = "#2C2E2B"
NEUTRAL_SUB = "#6F726B"
NEUTRAL_MUTED = "#9A9C94"
NEUTRAL_LINE = "#E6E3DB"


def _data_url(raw):
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _png(im):
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _rgba_sheet(im):
    """sprite 需要透明背景，单独走 RGBA 保存。"""
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 草案规范化
# ---------------------------------------------------------------------------

def normalize_theme(draft):
    """把前端编辑中的主题整理成渲染器需要的扁平结构，并拒绝非法值。"""
    if not isinstance(draft, dict):
        raise ValueError("theme 必须是 JSON 对象")

    colors = dict(cfg.MINIMAL_THEME["colors"])
    src = draft.get("colors") or {}
    if not isinstance(src, dict):
        raise ValueError("theme.colors 必须是对象")
    for k in cfg.COLOR_KEYS:
        v = src.get(k)
        if v is None:
            continue
        if not HEX_RE.match(str(v)):
            raise ValueError("颜色 %s 必须是 #RRGGBB：%r" % (k, v))
        colors[k] = str(v)

    registry = cfg.load_registry()
    valid_motifs = {m.get("id") for m in registry.get("motifs", [])}
    motif = str(draft.get("motif") or "circles")
    if valid_motifs and motif not in valid_motifs:
        motif = "circles"

    stickers = [s for s in (draft.get("stickers") or []) if s in cardgen.STICKERS]
    if not stickers:
        stickers = list(cfg.MINIMAL_THEME["stickers"])

    flat = dict(colors)
    flat.update(
        label=str(draft.get("label") or "DAILY CARD · 预览"),
        keywords=[str(x) for x in (draft.get("keywords") or [])],
        motif=motif,
        stickers=stickers,
        dark=bool(draft.get("dark", False)),
    )
    return flat


# ---------------------------------------------------------------------------
# 可读性诊断
# ---------------------------------------------------------------------------

def _lin(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _lum(color):
    r, g, b = cfg.hx(color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b):
    hi, lo = max(_lum(a), _lum(b)), min(_lum(a), _lum(b))
    return (hi + 0.05) / (lo + 0.05)


def diagnose(C):
    """返回 (提示列表, 对比度数值)。提示按严重程度排序。"""
    items = []
    ink_card = contrast(C["ink"], C["card"])
    sub_card = contrast(C["sub"], C["card"])
    pill_pair = contrast(C["pill_text"], C["pill"])
    card_bg = min(contrast(C["card"], C["bg1"]), contrast(C["card"], C["bg2"]))
    accent_bg = min(contrast(C["accent"], C["bg1"]), contrast(C["accent"], C["bg2"]))
    bg_light = (_lum(C["bg1"]) + _lum(C["bg2"])) / 2

    def add(level, text):
        items.append({"level": level, "text": text})

    if ink_card < 3.0:
        add("warn", "主文字与卡片底对比度仅 %.1f:1，标题会很难读；建议拉大 ink 与 card 的明暗差（≥ 4.5:1）。" % ink_card)
    elif ink_card < 4.5:
        add("warn", "主文字对比度 %.1f:1，略偏低（建议 ≥ 4.5:1），可加深 ink 或提亮 card。" % ink_card)
    else:
        add("ok", "主文字对比度 %.1f:1，标题清晰可读。" % ink_card)

    if sub_card < 3.0:
        add("warn", "副文字对比度 %.1f:1 偏低；副标题和日期容易糊，建议 sub 再深一点（≥ 3:1）。" % sub_card)

    if pill_pair < 4.5:
        add("warn", "标签底与标签字对比度 %.1f:1，标签上的小字可能看不清。" % pill_pair)

    if card_bg < 1.25:
        add("tip", "卡片底与背景很接近（%.2f:1），卡片边界会不明显；可让 card 更亮或更暗一些。" % card_bg)

    if accent_bg < 1.5:
        add("tip", "强调色与背景接近（%.2f:1），纹样和贴纸可能不够跳；试试提高 accent 的饱和度或明暗差。" % accent_bg)

    if not C["dark"] and bg_light < 0.22:
        add("warn", "背景整体偏深（亮度 %.0f%%），但「深色主题」仍是「否」；蒙版与文字会按浅色卡片处理，建议改成深色主题。" % (bg_light * 100))
    elif C["dark"] and bg_light > 0.58:
        add("warn", "背景整体偏亮（亮度 %.0f%%），但设成了「深色主题」；会套用深色蒙版，画面可能发灰。" % (bg_light * 100))
    else:
        add("ok", "背景明暗与「%s」设定一致。" % ("深色主题" if C["dark"] else "浅色主题"))

    if C["dark"] and _lum(C["card"]) > 0.55:
        add("tip", "深色主题下卡片底偏亮，标题与卡片会形成反色效果；若想要暗色卡片，把 card 调深。")

    numbers = {
        "ink_card": round(ink_card, 2),
        "sub_card": round(sub_card, 2),
        "pill_pair": round(pill_pair, 2),
        "card_bg": round(card_bg, 2),
        "accent_bg": round(accent_bg, 2),
        "bg_light": round(bg_light, 3),
    }
    return items, numbers


# ---------------------------------------------------------------------------
# 语义化配色示意图
# ---------------------------------------------------------------------------

def _fonts(q):
    bp, bi, rp, ri = cardgen.find_fonts()
    return {
        "big": cardgen.font_at(bp, 15 * q, bi),
        "small": cardgen.font_at(rp, 11 * q, ri),
        "tiny": cardgen.font_at(rp, 9 * q, ri),
        "title": cardgen.font_at(bp, 27 * q, bi),
        "sub": cardgen.font_at(rp, 13 * q, ri),
        "pill": cardgen.font_at(bp, 10 * q, bi),
    }


def render_legend(C, motif_label):
    """一张能看懂的图：左边是真实纹样 + 卡片层级，右边是 10 个颜色各管什么。"""
    q = 2
    W, H = 760 * q, 486 * q
    im = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(im)
    f = _fonts(q)

    d.text((18 * q, 12 * q), "配色语义图", font=f["big"], fill=NEUTRAL_INK)
    d.text((18 * q, 33 * q), "左边是纹样与卡片的真实效果，右边标注每个颜色用在哪里",
           font=f["tiny"], fill=NEUTRAL_MUTED)
    tag = "纹样：%s   ·   %s" % (motif_label, "深色主题" if C["dark"] else "浅色主题")
    bb = d.textbbox((0, 0), tag, font=f["small"])
    d.text((W - 18 * q - (bb[2] - bb[0]), 16 * q), tag, font=f["small"], fill=NEUTRAL_SUB)

    # --- 左侧：真实纹样背景 ---
    x0, y0, x1, y1 = 18 * q, 58 * q, 468 * q, 466 * q
    stage = cardgen.gradient(x1 - x0, y1 - y0, C["bg1"], C["bg2"])
    cardgen.draw_motif(stage, C, C["motif"], random.Random(7), 0.55 * q)

    cx0, cy0, cx1, cy1 = x0 + 52 * q, y0 + 58 * q, x1 - 52 * q, y1 - 58 * q
    # 卡片投影
    shadow = Image.new("RGBA", stage.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (cx0 + 4 * q, cy0 + 7 * q, cx1 + 4 * q, cy1 + 7 * q),
        radius=14 * q, fill=(20, 18, 16, 70))
    stage.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9 * q)))
    sd = ImageDraw.Draw(stage, "RGBA")
    sd.rounded_rectangle((cx0, cy0, cx1, cy1), radius=14 * q,
                         fill=cardgen.rgba(C["card"], 255))

    # 小标签
    px, py = cx0 + 22 * q, cy0 + 20 * q
    label = (C.get("label") or "DAILY CARD")[:14]
    lb = sd.textbbox((0, 0), label, font=f["pill"])
    sd.rounded_rectangle((px, py, px + (lb[2] - lb[0]) + 20 * q, py + 20 * q),
                         radius=10 * q, fill=cardgen.rgba(C["pill"], 255))
    sd.text((px + 10 * q, py + 3 * q), label, font=f["pill"],
            fill=cardgen.rgba(C["pill_text"], 255))

    sd.text((px, py + 40 * q), "示例标题", font=f["title"],
            fill=cardgen.rgba(C["ink"], 255))
    sd.text((px, py + 80 * q), "这句是副标题，用来看文字层级", font=f["sub"],
            fill=cardgen.rgba(C["sub"], 255))
    sd.line([(px, py + 112 * q), (cx1 - 22 * q, py + 112 * q)],
            fill=cardgen.rgba(C["accent"], 220), width=2 * q)
    for i, (k, name) in enumerate((("accent", "强调"), ("accent2", "辅助"), ("soft", "柔和"))):
        bx = px + i * 86 * q
        sd.ellipse((bx, py + 128 * q, bx + 14 * q, py + 142 * q),
                   fill=cardgen.rgba(C[k], 255))
        sd.text((bx + 19 * q, py + 126 * q), name, font=f["tiny"],
                fill=cardgen.rgba(C["sub"], 255))
    # 一个真实贴纸，展示贴纸取色
    st = cardgen.make_sticker(C["stickers"][0], 74 * q, C, angle=-10, alpha=235)
    cardgen.paste_sticker(stage, st, cx1 - 44 * q, cy1 - 42 * q)

    im.paste(stage.convert("RGB"), (x0, y0))
    d.rounded_rectangle((x0, y0, x1, y1), radius=10 * q,
                        outline=NEUTRAL_LINE, width=max(1, q))

    # --- 右侧：颜色角色表 ---
    rx = 486 * q
    for i, (k, name, desc) in enumerate(COLOR_ROLES):
        yy = (58 + i * 40) * q
        d.rounded_rectangle((rx, yy, rx + 26 * q, yy + 26 * q), radius=5 * q,
                            fill=C[k], outline=NEUTRAL_LINE, width=max(1, q // 2))
        d.text((rx + 34 * q, yy - 1 * q), name, font=f["small"], fill=NEUTRAL_INK)
        d.text((rx + 34 * q, yy + 14 * q), "%s  %s" % (C[k].upper(), desc),
               font=f["tiny"], fill=NEUTRAL_MUTED)

    return _png(im.resize((760, 486), Image.LANCZOS))


def render_sticker_strip(C, ids, name_map):
    q = 2
    W, H = 760 * q, 150 * q
    im = Image.new("RGBA", (W, H), cardgen.rgba(C["card"], 255))
    d = ImageDraw.Draw(im, "RGBA")
    f = _fonts(q)
    shown = list(ids)[:7]
    head = "贴纸在当前配色下的样子 · 共 %d 个%s" % (
        len(ids), "（展示前 %d 个）" % len(shown) if len(ids) > len(shown) else "")
    d.text((16 * q, 9 * q), head, font=f["small"],
           fill=cardgen.rgba(C["ink"], 255))
    for i, sid in enumerate(shown):
        cx = (62 + i * 100) * q
        st = cardgen.make_sticker(sid, 76 * q, C, alpha=255)
        cardgen.paste_sticker(im, st, cx, 76 * q)
        nm = (name_map.get(sid) or sid)[:6]
        bb = d.textbbox((0, 0), nm, font=f["tiny"])
        d.text((cx - (bb[2] - bb[0]) / 2, 120 * q), nm, font=f["tiny"],
               fill=cardgen.rgba(C["sub"], 255))
    d.rectangle((0, 0, W - 1, H - 1), outline=cardgen.rgba(C["accent"], 130), width=2 * q)
    return _png(im.resize((760, 150), Image.LANCZOS))


def render_sticker_sheet(C, order, cell=76, cols=7):
    """全量贴纸按当前配色排成 sprite，前端用 background-position 切片。"""
    q = 2
    rows = max(1, math.ceil(len(order) / cols))
    im = Image.new("RGBA", (cols * cell * q, rows * cell * q), (0, 0, 0, 0))
    plate = ImageDraw.Draw(im)
    for i in range(len(order)):
        gx, gy = (i % cols) * cell * q, (i // cols) * cell * q
        # 极淡中性底板：让白色/浅色贴纸在浅色图标格里也能看清轮廓
        plate.rounded_rectangle(
            (gx + 5 * q, gy + 5 * q, gx + (cell - 5) * q, gy + (cell - 5) * q),
            radius=9 * q, fill=(110, 106, 96, 16))
    for i, sid in enumerate(order):
        cx = (i % cols) * cell * q + cell * q / 2
        cy = (i // cols) * cell * q + cell * q / 2
        st = cardgen.make_sticker(sid, int(58 * q), C, alpha=255)
        cardgen.paste_sticker(im, st, cx, cy)
    return _rgba_sheet(im), cols, rows, cell


# ---------------------------------------------------------------------------
# 组装预览结果
# ---------------------------------------------------------------------------

def build_preview(data):
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    C = normalize_theme(data.get("theme"))
    registry = cfg.load_registry()
    motif_map = {m.get("id"): m for m in registry.get("motifs", [])}
    motif_info = motif_map.get(C["motif"]) or {}
    name_map = {s.get("id"): s.get("name") for s in registry.get("stickers", [])}
    order = [s["id"] for s in registry.get("stickers", []) if s.get("id") in cardgen.STICKERS]
    if not order:
        order = sorted(cardgen.STICKERS)

    platform = data.get("platform") or "moments"
    if platform not in cardgen.PLATFORMS:
        raise ValueError("未知平台：%s" % platform)
    title = (data.get("title") or "把普通的日子，过得响亮一点").strip() or "示例标题"
    subtitle = data.get("subtitle") or "这句是副标题，用来预览文字层级"
    date = data.get("date") or None
    if isinstance(date, str) and not DATE_RE.match(date):
        date = None
    try:
        seed = int(data["seed"]) if data.get("seed") not in (None, "") else 7
    except (TypeError, ValueError):
        seed = 7

    # 固定种子：调颜色时构图不跳，方便对比前后差异
    settings = dict(cfg.load_settings())
    settings["supersample"] = 1                 # 预览用 1x，速度约快 4 倍
    out = os.path.join(cfg.uploads_dir(), ".draft-%s.png" % uuid.uuid4().hex[:10])
    try:
        cardgen.render(title, subtitle, date=date, platform=platform,
                       theme_name=DRAFT_ID, brand=data.get("brand") or "",
                       out=out, seed=seed, themes={DRAFT_ID: C}, settings=settings)
        with open(out, "rb") as fh:
            card = fh.read()
    finally:
        if os.path.exists(out):
            os.remove(out)

    sheet_png, cols, rows, cell = render_sticker_sheet(C, order)
    items, numbers = diagnose(C)
    return {
        "ok": True,
        "card": _data_url(card),
        "legend": _data_url(render_legend(C, motif_info.get("name") or C["motif"])),
        "stickers": _data_url(render_sticker_strip(C, C["stickers"], name_map)),
        "sticker_sheet": _data_url(sheet_png),
        "sheet": {"cols": cols, "rows": rows, "cell": cell, "order": order},
        "diagnostics": items,
        "contrast": numbers,
        "motif": {"id": C["motif"], "name": motif_info.get("name") or C["motif"],
                  "desc": motif_info.get("desc") or ""},
        "dark": C["dark"],
        "platform": platform,
        "size": list(cardgen.PLATFORMS[platform][:2]),
        "draft_only": True,                     # 明确告诉调用方：没有写配置文件
    }
