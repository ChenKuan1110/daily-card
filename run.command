#!/bin/bash
# 双击运行：问答式输入标题 / 副标题，生成卡片后自动打开 output 文件夹
cd "$(dirname "$0")" || exit 1

if ! python3 -c "import PIL" >/dev/null 2>&1; then
  echo "首次运行，正在安装依赖 Pillow ..."
  python3 -m pip install --quiet Pillow || {
    echo "安装失败，请手动执行： python3 -m pip install Pillow"
    read -r -p "按回车键退出"
    exit 1
  }
fi

python3 cardgen.py --interactive
if [ $? -eq 0 ]; then
  open "$(pwd)/output"
fi

echo ""
read -r -p "按回车键关闭窗口"
