#!/bin/bash
# 双击启动 daily-card 网页后台，并自动打开浏览器
cd "$(dirname "$0")" || exit 1

if ! python3 -c "import PIL" >/dev/null 2>&1; then
  echo "首次运行，正在安装依赖 Pillow ..."
  python3 -m pip install --quiet Pillow || {
    echo "安装失败，请手动执行： python3 -m pip install Pillow"
    read -r -p "按回车键退出"
    exit 1
  }
fi

echo "  后台地址： http://127.0.0.1:8777"
echo "  停止服务： 在本窗口按 Ctrl+C"
echo ""
python3 server.py --open
