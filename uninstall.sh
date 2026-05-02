#!/usr/bin/env bash
set -euo pipefail

# Find and remove the workbrief symlink from PATH
IFS=':' read -ra PATH_DIRS <<< "$PATH"
found=0
for dir in "${PATH_DIRS[@]}"; do
    target="$dir/workbrief"
    if [ -L "$target" ]; then
        echo "移除 $target"
        rm "$target"
        found=1
    fi
done

if [ "$found" -eq 0 ]; then
    echo "未找到 workbrief 命令。"
else
    echo "卸载完成。"
fi
