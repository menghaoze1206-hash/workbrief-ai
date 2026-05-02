#!/usr/bin/env python3
"""WorkBrief AI — 根据 Git diff 生成中文研发周报（CLI 版）。"""

import argparse
import os
import subprocess
import sys
import urllib.error

from core import (
    MAX_DIFF_BYTES,
    REF_PATTERN,
    build_diff_args,
    build_weekly_prompt,
    call_deepseek,
    count_files,
    get_git_versions,
    run_git,
    summarize_diff,
)


def pick_interactive(no_color=False):
    """交互式选择 diff 范围，返回 (mode, base)。"""
    c = "" if no_color else "\033[36m"
    y = "" if no_color else "\033[33m"
    r = "" if no_color else "\033[0m"

    try:
        current_branch, branches, commits = get_git_versions()
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or str(e)
        print(f"Git 错误：{msg}", file=sys.stderr)
        sys.exit(1)

    options = [
        ("w", "工作区 vs HEAD", "working", "HEAD"),
        ("s", "暂存区", "staged", "HEAD"),
    ]

    print(f"\n{c}当前分支：{r}{current_branch}\n")
    print(f"{y}快捷模式：{r}")
    for key, label, _, _ in options:
        print(f"  [{key}]  {label}")

    print(f"\n{y}分支：{r}")
    for i, branch in enumerate(branches):
        key = str(i + 1)
        options.append((key, branch, "range", branch))
        print(f"  [{key:>2}]  {branch}")

    print(f"\n{y}最近提交：{r}")
    for j, commit in enumerate(commits):
        key = str(len(branches) + j + 1)
        options.append(
            (
                key,
                f"{commit['short_sha']} {commit['date']} {commit['subject']}",
                "range",
                commit["sha"],
            )
        )
        print(f"  [{key:>2}]  {commit['short_sha']} {commit['date']} {commit['subject']}")

    print()
    while True:
        try:
            choice = input("选择编号 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if not choice:
            continue

        for key, label, mode, base in options:
            if choice.lower() == key.lower():
                return mode, base

        print(f"无效选择：{choice}", file=sys.stderr)


def generate_report(mode, base, to, diff_only, dry_run, output_file, no_color):
    c = "" if no_color else "\033[36m"
    r = "" if no_color else "\033[0m"
    y = "" if no_color else "\033[33m"
    g = "" if no_color else "\033[32m"

    if mode == "range" and not REF_PATTERN.match(to):
        print(f"错误：目标版本名包含不支持的字符: {to}", file=sys.stderr)
        sys.exit(1)

    if not REF_PATTERN.match(base):
        print(f"错误：版本名包含不支持的字符: {base}", file=sys.stderr)
        sys.exit(1)

    try:
        run_git(["rev-parse", "--show-toplevel"])
        stat_args, diff_args = build_diff_args(mode, base, to=to)
        stat = run_git(stat_args)
        diff = run_git(diff_args, max_bytes=MAX_DIFF_BYTES)
    except subprocess.CalledProcessError as e:
        msg = e.stderr.strip() or e.stdout.strip() or str(e)
        print(f"Git 错误：{msg}", file=sys.stderr)
        sys.exit(1)

    full_diff = f"{stat}\n\n{diff}".strip()
    truncated = len(diff.encode("utf-8")) >= MAX_DIFF_BYTES
    files_changed = count_files(stat)

    if not full_diff:
        print("未发现代码变更。", file=sys.stderr)
        sys.exit(0)

    mode_label = {
        "working": "工作区 vs HEAD",
        "staged": "暂存区",
        "range": f"{base}...{to}",
    }[mode]

    if diff_only:
        print(f"{c}范围：{r}{mode_label}　{c}文件：{r}{files_changed}", file=sys.stderr)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(full_diff + "\n")
            print(f"Diff 已写入 {output_file}", file=sys.stderr)
        else:
            print(full_diff)
        return

    prompt = build_weekly_prompt(full_diff)

    if dry_run:
        print(f"{c}--- DRY RUN: 以下是将发送给 DeepSeek 的 prompt ---{r}")
        print(prompt)
        return

    print(f"{c}范围：{r}{mode_label}　{c}文件：{r}{files_changed}　{c}截断：{r}{'是' if truncated else '否'}", file=sys.stderr)
    print(f"{y}正在调用 DeepSeek 生成周报...{r}", file=sys.stderr)

    try:
        report = call_deepseek(prompt)
    except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
        if hasattr(e, "read"):
            detail = e.read().decode("utf-8", errors="ignore")[:200]
        else:
            detail = str(e)
        print(f"{y}DeepSeek 调用失败，使用本地模板：{detail}{r}", file=sys.stderr)
        report = summarize_diff(full_diff)
    else:
        if not report:
            print(f"{y}DeepSeek 返回空内容，使用本地模板。{r}", file=sys.stderr)
            report = summarize_diff(full_diff)
        else:
            print(f"{g}生成完成。{r}", file=sys.stderr)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"周报已写入 {output_file}", file=sys.stderr)
    else:
        print(report)


def main():
    parser = argparse.ArgumentParser(
        description="根据 Git diff 生成中文研发周报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  wk -i                    交互选择 diff 范围
  wk                        工作区 vs HEAD
  wk -s                     仅暂存区
  wk -b main                从 main 到 HEAD
  wk -b v1.0 -t v2.0        从 v1.0 到 v2.0
  wk -b main -d             只看 diff
  wk -b main --dry          预览 prompt 不调 API
  wk -l                     列出可用的分支和提交
  wk -o weekly.md           输出到文件

环境变量：
  DEEPSEEK_BASE_URL               API 地址（默认 https://api.deepseek.com）
  DEEPSEEK_MODEL                  模型名称（默认 deepseek-v4-flash）
  DEEPSEEK_TEMPERATURE            温度参数（默认 0.35）
  DEEPSEEK_API_KEY                API Key（优先级最高）
        """.strip(),
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["working", "staged", "range"],
        default="working",
        help="diff 范围 (默认 working)",
    )
    parser.add_argument(
        "--base", "-b",
        default=None,
        help="起始版本，指定后自动启用 range 模式 (默认 main)",
    )
    parser.add_argument(
        "--to", "-t",
        default=None,
        help="目标版本 (默认 HEAD)",
    )
    parser.add_argument(
        "--staged", "-s",
        action="store_true",
        help="等同于 --mode staged",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互式选择 diff 范围",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出可用的分支和最近提交",
    )
    parser.add_argument(
        "--diff-only", "-d",
        action="store_true",
        help="只输出 diff，不调用 AI 生成周报",
    )
    parser.add_argument(
        "--dry-run", "--dry",
        action="store_true",
        help="预览将要发送的 prompt，不调用 API",
    )
    parser.add_argument(
        "--output", "-o",
        help="输出到文件，默认输出到终端",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用 ANSI 颜色输出",
    )

    args = parser.parse_args()

    if args.list:
        try:
            current_branch, branches, commits = get_git_versions()
        except subprocess.CalledProcessError as e:
            msg = e.stderr.strip() or e.stdout.strip() or str(e)
            print(f"Git 错误：{msg}", file=sys.stderr)
            sys.exit(1)

        print(f"当前分支：{current_branch}")
        print(f"\n分支：")
        for branch in branches:
            print(f"  {branch}")
        print(f"\n最近提交：")
        for commit in commits:
            print(f"  {commit['short_sha']} {commit['date']} {commit['subject']}")
        return

    if args.interactive:
        mode, base = pick_interactive(args.no_color)
        to = "HEAD"
    elif args.staged:
        mode, base, to = "staged", "HEAD", "HEAD"
    elif args.base is not None or args.to is not None or args.mode == "range":
        mode = "range"
        base = args.base or "main"
        to = args.to or "HEAD"
    else:
        mode, base, to = "working", "HEAD", "HEAD"

    generate_report(mode, base, to, args.diff_only, args.dry_run, args.output, args.no_color)


if __name__ == "__main__":
    main()
