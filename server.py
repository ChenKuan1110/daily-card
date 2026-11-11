#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily-card 本地网页后台

  python3 server.py              # 默认 http://127.0.0.1:8777
  python3 server.py --port 9000 --open

只监听本机回环地址，不对外暴露；所有配置读写都落在项目目录内。
API 也可以被 agent / curl 直接调用，详见 SKILL.md。
"""

from __future__ import annotations

import argparse
import base64
import datetime
import io
import json
import os
import re
import sys
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cardconfig as cfg
import cardgen
import cardpreview

BASE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE, "web")
MAX_BODY = 24 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _upload_path(image_id):
    """把 image_id 安全映射到 uploads/ 下的真实文件。"""
    if not image_id or not ID_RE.match(str(image_id)):
        return None
    d = cfg.uploads_dir()
    for name in os.listdir(d):
        if name.startswith(image_id + "."):
            return os.path.join(d, name)
    return None


def _save_data_url(data_url):
    """前端用 FileReader 传 base64，避免引入 multipart 解析依赖。"""
    m = re.match(r"^data:image/([A-Za-z0-9.+-]+);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("图片数据格式不正确（需要 data:image/...;base64,...）")
    kind = m.group(1).lower()
    if kind == "jpg":
        kind = "jpeg"
    if kind not in ("png", "jpeg", "webp"):
        raise ValueError("仅支持 png / jpg / webp 图片")
    ext = "jpg" if kind == "jpeg" else kind
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("图片超过 20MB")
    image_id = uuid.uuid4().hex[:16]
    path = os.path.join(cfg.uploads_dir(), image_id + "." + ext)
    with open(path, "wb") as f:
        f.write(raw)
    # 校验确实是图片
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    return image_id, path


def _render_payload(data, save=False):
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    platform = data.get("platform") or "xhs"
    if platform not in cardgen.PLATFORMS:
        raise ValueError("未知平台：%s" % platform)

    theme_name = data.get("theme") or "auto"
    themes = cfg.load_themes()
    if theme_name == "auto":
        theme_name = cardgen.pick_theme(
            title + " " + (data.get("subtitle") or ""), "auto", themes,
            cfg.default_theme_id())
    if theme_name not in themes:
        raise ValueError("未知主题：%s" % theme_name)

    bg_path = None
    if data.get("bg_image_id"):
        bg_path = _upload_path(data["bg_image_id"])
        if not bg_path:
            raise ValueError("背景图不存在，请重新上传")
    elif data.get("bg_path"):
        p = os.path.expanduser(str(data["bg_path"]))
        if not os.path.isfile(p):
            raise ValueError("找不到背景图：%s" % p)
        bg_path = p

    scheme = data.get("bg_scheme", 0)
    if scheme in (None, ""):
        scheme = 0
    date = data.get("date") or None
    seed = data.get("seed")
    if seed in ("", None):
        seed = None
    else:
        seed = int(seed)

    if save:
        out_dir = cfg.output_dir()
        os.makedirs(out_dir, exist_ok=True)
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")[:18] or "card"
        out = os.path.join(out_dir, "%s-%s-%s.png" % (
            safe, date or datetime.date.today().isoformat(), platform))
    else:
        out = os.path.join(cfg.uploads_dir(), ".preview-%s.png" % uuid.uuid4().hex[:10])

    # 每次请求都重新读配置，后台保存后立刻生效
    out_path, used = cardgen.render(
        title, data.get("subtitle") or "", date=date, platform=platform,
        theme_name=theme_name, bg_image=bg_path, brand=data.get("brand") or "",
        out=out, seed=seed, themes=themes, settings=cfg.load_settings(),
        bg_scheme=scheme, dark_override=data.get("dark_override"))

    try:
        with open(out_path, "rb") as f:
            png = f.read()
    finally:
        if not save and os.path.exists(out_path):
            os.remove(out_path)     # 预览临时图用完即删，不在 uploads 里堆积
    return {
        "ok": True,
        "png": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
        "path": out_path,
        "theme": used,
        "platform": platform,
        "size": list(cardgen.PLATFORMS[platform][:2]),
        "bytes": len(png),
    }


def _sticker_png(sticker_id, theme_id, size=88):
    themes = cfg.load_themes()
    C = themes.get(theme_id) or themes[cfg.default_theme_id()]
    if sticker_id not in cardgen.STICKERS:
        raise ValueError("未知贴纸：%s" % sticker_id)
    im = cardgen.make_sticker(sticker_id, int(size), C, alpha=255)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "DailyCard/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("DAILY_CARD_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=200):
        self._send(status, data)

    def _error(self, msg, status=400):
        self._json({"ok": False, "error": str(msg)}, status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)
        try:
            if path == "/api/bootstrap":
                return self._json({
                    "ok": True,
                    "themes_doc": cfg.load_doc(),
                    "settings": cfg.load_settings(),
                    "registry": cfg.load_registry(),
                    "platforms": {k: {"w": v[0], "h": v[1], "desc": v[2]}
                                  for k, v in cardgen.PLATFORMS.items()},
                    "sticker_ids": sorted(cardgen.STICKERS),
                    "config_dir": cfg.config_dir(),
                    "output_dir": cfg.output_dir(),
                })
            if path == "/api/sticker":
                png = _sticker_png((q.get("id") or ["sparkle"])[0],
                                   (q.get("theme") or ["quote"])[0],
                                   int((q.get("size") or ["88"])[0]))
                return self._send(200, png, "image/png")
            if path == "/api/schemes":
                image_id = (q.get("image_id") or [None])[0]
                p = _upload_path(image_id) if image_id else None
                if not p:
                    return self._error("缺少有效的 image_id")
                return self._json({"ok": True, "image_id": image_id,
                                   "schemes": cfg.extract_schemes(p)})
            if path.startswith("/api/"):
                return self._error("未知接口：%s" % path, 404)

            # 静态文件
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            if ".." in rel or rel.startswith("/"):
                return self._error("非法路径", 403)
            full = os.path.join(WEB_DIR, rel)
            if not os.path.isfile(full):
                return self._error("文件不存在：%s" % rel, 404)
            ext = os.path.splitext(full)[1].lower()
            with open(full, "rb") as f:
                return self._send(200, f.read(), MIME.get(ext, "application/octet-stream"))
        except Exception as e:
            traceback.print_exc()
            return self._error(e)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._body()
            if path == "/api/config/themes":
                ok, msg = cfg.save_doc(data.get("themes_doc") or data)
                return self._json({"ok": ok, "message": msg} if ok
                                  else {"ok": False, "error": msg}, 200 if ok else 400)
            if path == "/api/config/settings":
                ok, msg = cfg.save_settings(data.get("settings") or data)
                return self._json({"ok": ok, "message": msg})
            if path == "/api/config/reset":
                ok, msg = cfg.reset_themes()
                return self._json({"ok": ok, "message": msg,
                                   "themes_doc": cfg.load_doc()})
            if path == "/api/schemes":
                if data.get("image"):
                    image_id, p = _save_data_url(data["image"])
                elif data.get("path"):
                    p = os.path.expanduser(str(data["path"]))
                    if not os.path.isfile(p):
                        return self._error("找不到背景图：%s" % p)
                    image_id = os.path.splitext(os.path.basename(p))[0]
                    image_id = re.sub(r"[^A-Za-z0-9_\-]", "", image_id)[:24] or "bg"
                    dest = os.path.join(cfg.uploads_dir(), image_id + ".png")
                    from PIL import Image
                    Image.open(p).convert("RGB").save(dest)
                    p = dest
                else:
                    return self._error("需要提供 image(dataURL) 或 path")
                return self._json({"ok": True, "image_id": image_id,
                                   "schemes": cfg.extract_schemes(p)})
            if path in ("/api/render", "/api/save"):
                result = _render_payload(data, save=(path == "/api/save"))
                return self._json(result)
            if path == "/api/theme-preview":
                # 预览尚未保存的主题草案：只读内存，不触碰 config/themes.json
                return self._json(cardpreview.build_preview(data))
            if path == "/api/reveal":
                target = data.get("path") or cfg.output_dir()
                if not os.path.exists(target):
                    os.makedirs(target, exist_ok=True)
                if sys.platform == "darwin":
                    os.system('open "%s"' % target.replace('"', '\\"'))
                elif sys.platform == "win32":
                    os.startfile(target)
                return self._json({"ok": True, "path": target})
            return self._error("未知接口：%s" % path, 404)
        except SystemExit as e:
            return self._error(e)
        except Exception as e:
            traceback.print_exc()
            return self._error(e)


def main():
    ap = argparse.ArgumentParser(description="daily-card 本地网页后台")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    cfg.ensure_config()
    url = "http://%s:%d" % (args.host, args.port)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("  🐾 daily-card 后台已启动")
    print("     地址：%s" % url)
    print("     配置：%s" % cfg.config_dir())
    print("     输出：%s" % cfg.output_dir())
    print("     Ctrl+C 停止\n")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
