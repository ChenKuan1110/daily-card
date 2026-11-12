#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟 Linux 各发行版的字体命名/安装位置差异，验证字体探测的兜底路径。

不依赖真实系统字体：临时目录造文件名、mock fontconfig 输出，
因此 macOS / Linux CI 上都能跑。由 scripts/selfcheck.sh 第 9 步调用。
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cardgen


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb"):
        pass
    return path


def _linux_env(script, scan_dirs=(), fc_stdout=None):
    """切断 macOS 精确名快路径，按需要注入 fontconfig 输出与扫描目录。"""
    patches = [
        mock.patch.object(cardgen, "FONT_CANDIDATES", []),
        mock.patch.object(cardgen, "FONT_DIRS", []),
        mock.patch.object(cardgen, "FONT_SCAN_DIRS", list(scan_dirs)),
    ]
    if fc_stdout is None:
        patches.append(mock.patch("subprocess.run", side_effect=FileNotFoundError))
    else:
        patches.append(mock.patch(
            "subprocess.run",
            return_value=mock.Mock(returncode=0, stdout=fc_stdout)))
    for p in patches:
        p.start()
    try:
        return script()
    finally:
        for p in reversed(patches):
            p.stop()


def main():
    checks = []

    # 1. fontconfig 兜底：RHEL 系常见的 .otf + 非标准文件名 + 非标准目录
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "usr/share/fonts/google-noto-cjk")
        bold = _touch(os.path.join(d, "NotoSansCJKsc-Bold.otf"))
        reg = _touch(os.path.join(d, "NotoSansCJKsc-Regular.otf"))
        fc = ("%s|Noto Sans CJK SC|Bold\n%s|Noto Sans CJK SC|Regular\n"
              % (bold, reg))
        r = _linux_env(lambda: cardgen.resolve_fonts(), fc_stdout=fc)
        checks.append(("fontconfig 命中非标准文件名",
                       r[4] == "fontconfig" and r[0] == bold and r[2] == reg))

    # 2. 没有 fontconfig 时，递归扫描兜底能找到嵌套目录里的字体
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "truetype/noto")
        bold = _touch(os.path.join(d, "NotoSansCJK-Bold.ttc"))
        reg = _touch(os.path.join(d, "NotoSansCJK-Regular.ttc"))
        r = _linux_env(lambda: cardgen.resolve_fonts(), scan_dirs=[td])
        checks.append(("无 fontconfig 时递归扫描兜底",
                       r[4] == "glob" and r[0] == bold and r[2] == reg))

    # 3. 只装了常规体（缺粗体）时，仍能退化成单文件渲染而不是直接失败
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, "opentype/noto")
        reg = _touch(os.path.join(d, "NotoSansCJK-Regular.ttc"))
        r = _linux_env(lambda: cardgen.resolve_fonts(), scan_dirs=[td])
        checks.append(("缺粗体时单文件退化",
                       r[4] == "glob-single" and r[0] == reg and r[2] == reg))

    # 4. 显式环境变量优先级最高，且不依赖任何探测
    with tempfile.TemporaryDirectory() as td:
        bold = _touch(os.path.join(td, "My-Bold.ttf"))
        reg = _touch(os.path.join(td, "My-Regular.ttf"))
        with mock.patch.dict(os.environ, {
                "DAILY_CARD_FONT_BOLD": bold, "DAILY_CARD_FONT": reg}):
            r = _linux_env(lambda: cardgen.resolve_fonts())
        checks.append(("环境变量显式配置优先",
                       r[4] == "explicit" and r[0] == bold and r[2] == reg))

    # 5. 显式路径写错时不能静默，诊断里要能看见
    with mock.patch.dict(os.environ, {
            "DAILY_CARD_FONT_BOLD": "/no/such/Bold.ttc",
            "DAILY_CARD_FONT": "/no/such/Regular.ttc"}):
        diag = cardgen.font_diagnostics()
    checks.append(("显式路径错误进入提示",
                   any("不存在" in h for h in diag["hints"])))

    # 6. 一个中文字体都没有时，报错带安装建议与诊断命令
    with mock.patch.dict(os.environ, {
            "DAILY_CARD_FONT_BOLD": "", "DAILY_CARD_FONT": ""}):
        try:
            _linux_env(lambda: cardgen.find_fonts())
            msg = ""
        except cardgen.FontNotFound as e:
            msg = str(e)
    checks.append(("无字体时给出可操作建议",
                   "找不到中文字体" in msg and "fonts-noto-cjk" in msg
                   and "--font-diagnose" in msg))

    # 7. 正常环境下 find_fonts 仍返回四元组，且文件真实存在
    b, bi, r, ri = cardgen.find_fonts()
    checks.append(("find_fonts 保持四元组契约",
                   bool(b and r) and os.path.isfile(b) and os.path.isfile(r)
                   and isinstance(bi, int) and isinstance(ri, int)))

    width = max(len(name) for name, _ in checks)
    for name, ok in checks:
        print("        %-*s %s" % (width, name, "OK" if ok else "FAIL"))
    failed = [name for name, ok in checks if not ok]
    if failed:
        print("        失败项：%s" % "、".join(failed))
        return 1
    print("        %d 项全部通过（模拟 Linux 字体命名差异）" % len(checks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
