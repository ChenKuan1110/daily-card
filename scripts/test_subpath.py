#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 nginx 子路径部署，验证静态分离与 API 前缀剥离。

不依赖 nginx：进程内启动一个 --api-only 后端与一个剥前缀代理，
复现 docs/DEPLOY.md 中 location /daily-card/ 与 /daily-card/api/ 的规则。
既用于本地回归，也由 scripts/selfcheck.sh 在 CI 中调用。
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cardconfig as cfg
import server

PREFIX = "/daily-card"
WEB = os.path.join(BASE, "web")
BACKEND_PORT = [0]


class ProxyHandler(BaseHTTPRequestHandler):
    """行为等价于 nginx：静态走 alias，API 剥前缀后转发。"""

    def log_message(self, *args):
        pass

    def _handle(self, method):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == PREFIX:
            self.send_response(301)
            self.send_header("Location", PREFIX + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path.startswith(PREFIX + "/api/"):
            target = "http://127.0.0.1:%d%s" % (BACKEND_PORT[0], path[len(PREFIX):])
            if parsed.query:
                target += "?" + parsed.query
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            req = urllib.request.Request(
                target, data=body, method=method,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    status, ct, out = r.status, r.headers.get("Content-Type", ""), r.read()
            except urllib.error.HTTPError as e:
                status, ct, out = e.code, e.headers.get("Content-Type", ""), e.read()
            self.send_response(status)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return

        if path.startswith(PREFIX + "/"):
            rel = path[len(PREFIX) + 1:] or "index.html"
            full = os.path.join(WEB, rel)
            if ".." in rel or not os.path.isfile(full):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            with open(full, "rb") as f:
                out = f.read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.status, r.read()


def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read()


def status_only(fn, *args):
    try:
        return fn(*args)[0]
    except urllib.error.HTTPError as e:
        return e.code


def main():
    cfg.ensure_config()
    server.Handler.api_only = True

    backend = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    BACKEND_PORT[0] = backend.server_address[1]
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    pport = proxy.server_address[1]
    threading.Thread(target=proxy.serve_forever, daemon=True).start()

    root = "http://127.0.0.1:%d" % pport
    checks = []
    try:
        conn = http.client.HTTPConnection("127.0.0.1", pport, timeout=10)
        conn.request("GET", PREFIX)
        r = conn.getresponse()
        r.read()
        checks.append(("尾斜杠 301 重定向",
                       r.status == 301 and r.getheader("Location") == PREFIX + "/"))
        conn.close()

        st, body = get(root + PREFIX + "/")
        html = body.decode("utf-8")
        checks.append(("页面返回相对资源路径",
                       st == 200 and 'href="style.css"' in html
                       and 'src="app.js"' in html and 'href="/' not in html))

        st, css = get(root + PREFIX + "/style.css")
        checks.append(("style.css 由静态目录提供", st == 200 and len(css) > 1000))

        st, js = get(root + PREFIX + "/app.js")
        checks.append(("app.js 含运行时 BASE", st == 200 and b"const BASE" in js))

        st, body = get(root + PREFIX + "/api/health")
        d = json.loads(body)
        checks.append(("/api/health 剥前缀转发",
                       st == 200 and d.get("mode") == "api-only"
                       and d.get("serves_static") is False))

        st, body = get(root + PREFIX + "/api/bootstrap")
        d = json.loads(body)
        checks.append(("/api/bootstrap 返回主题",
                       st == 200 and len(d.get("themes_doc", {}).get("themes", {})) > 0))

        st, body = get(root + PREFIX + "/api/sticker?id=book&theme=study")
        checks.append(("贴纸图标 PNG", st == 200 and body[:4] == b"\x89PNG"))

        theme = cfg.load_doc()["themes"]["study"]
        st, body = post(root + PREFIX + "/api/theme-preview",
                        {"theme": theme, "title": "子路径回归",
                         "subtitle": "POST 请求体转发", "platform": "moments"})
        d = json.loads(body)
        checks.append(("POST 主题草案预览",
                       st == 200 and d.get("draft_only") is True and "card" in d))

        b = "http://127.0.0.1:%d" % BACKEND_PORT[0]
        checks.append(("后端不再托管静态页面",
                       status_only(get, b + "/index.html") == 404))
        checks.append(("远程模式禁用 /api/reveal",
                       status_only(post, b + "/api/reveal", {}) == 403))
    finally:
        proxy.shutdown()
        proxy.server_close()
        backend.shutdown()
        backend.server_close()

    width = max(len(name) for name, _ in checks)
    for name, ok in checks:
        print("        %-*s %s" % (width, name, "OK" if ok else "FAIL"))
    failed = [name for name, ok in checks if not ok]
    if failed:
        print("        失败项：%s" % "、".join(failed))
        return 1
    print("        %d 项全部通过（模拟前缀 %s）" % (len(checks), PREFIX))
    return 0


if __name__ == "__main__":
    sys.exit(main())
