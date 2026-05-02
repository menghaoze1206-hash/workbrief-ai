#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/workbrief.py"

if [ ! -f "$SRC" ]; then
    echo "错误：找不到 workbrief.py" >&2
    exit 1
fi

chmod +x "$SRC"

# Pick the first writable bin directory already in PATH
BIN_DIR=""
IFS=':' read -ra PATH_DIRS <<< "$PATH"
for dir in "${PATH_DIRS[@]}"; do
    if [ -d "$dir" ] && [ -w "$dir" ] && [[ "$dir" =~ /bin$ ]]; then
        BIN_DIR="$dir"
        break
    fi
done

if [ -z "$BIN_DIR" ]; then
    echo "未找到可写的 bin 目录，使用 ~/.local/bin" >&2
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
fi

ln -sf "$SRC" "$BIN_DIR/workbrief"

echo ""
echo "安装完成！现在可以在任意 Git 仓库目录使用："
echo "  workbrief              # 工作区 vs HEAD"
echo "  workbrief -s           # 暂存区"
echo "  workbrief -b main      # main...HEAD"
echo "  workbrief -d           # 只看 diff"
echo "  workbrief -o w.md      # 输出到文件"
