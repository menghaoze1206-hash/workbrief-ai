#!/usr/bin/env python3
"""WorkBrief AI — 根据 Git diff 生成中文研发周报（CLI 版）。"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

MAX_DIFF_BYTES = 240_000
MAX_PROMPT_CHARS = 16_000
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
CLAUDE_SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/\-]+$")


def run_git(args, max_bytes=None):
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = result.stdout
    if max_bytes and len(output.encode("utf-8")) > max_bytes:
        encoded = output.encode("utf-8")[:max_bytes]
        output = encoded.decode("utf-8", errors="ignore")
        output += "\n\n[diff 已截断]"
    return output


def build_diff_args(mode, base):
    if mode == "range":
        ref = f"{base}...HEAD"
        return ["diff", "--stat", ref, "--"], ["diff", ref, "--"]
    if mode == "staged":
        return ["diff", "--cached", "--stat", "--"], ["diff", "--cached", "--"]
    return ["diff", "--stat", "HEAD", "--"], ["diff", "HEAD", "--"]


def count_files(stat):
    for line in reversed(stat.splitlines()):
        match = re.search(r"(\d+) files? changed", line)
        if match:
            return int(match.group(1))
    return 0


def get_deepseek_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if key:
        return key.removeprefix("Bearer ").strip()

    try:
        with open(CLAUDE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        raise ValueError("未找到 Claude Code 配置文件，无法读取 API Key。")

    env = settings.get("env", {})
    key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("Claude Code 配置中未找到 ANTHROPIC_AUTH_TOKEN。")
    return key.removeprefix("Bearer ").strip()


def build_weekly_prompt(git_diff):
    diff_text = git_diff[:MAX_PROMPT_CHARS]
    truncated = (
        "\n[diff 已截断，仅保留前 16000 字符]" if len(git_diff) > MAX_PROMPT_CHARS else ""
    )
    return f"""你是一名擅长写周报的中文助手。你的读者是不懂代码的老板，需要你根据 Git diff 反推本周的工作成果。

要求：
1. 每条用老板能看懂的业务语言描述，禁用技术术语（如 refactor、bugfix、API、组件、模块、依赖等）。
2. 如果 diff 来自某个功能模块，推断这个改动对用户/客户有什么影响，而不是描述改了什么文件。
3. 当实在无法判断业务含义时，用"优化了 XX 相关功能"一笔带过，不要提文件路径或函数名。
4. 输出 3-6 条要点，每条一句话，直接可贴周报。

Git diff：
{diff_text}{truncated}"""


def call_deepseek(prompt):
    api_key = get_deepseek_api_key()
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": "你只输出可直接提交的中文周报正文。面向老板，用业务语言，不提技术细节。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.35,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def summarize_diff(diff):
    """本地兜底：统计文件、增删行数。"""
    files = set()
    additions = 0
    deletions = 0

    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            m = line.rfind(" b/")
            if m != -1:
                files.add(line[m + 3:])
        elif line.startswith("+++ b/"):
            files.add(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    file_list = sorted(files)[:8]
    lines = [
        "## 周报（本地模板）",
        "",
        f"- 本周完成了一批代码变更，涉及 {len(files) or '若干'} 个文件，新增 {additions} 行、删除 {deletions} 行。",
    ]
    for f in file_list:
        lines.append(f"- 调整了 `{f}` 相关逻辑。")
    if len(files) > 8:
        lines.append(f"- ... 以及其他 {len(files) - 8} 个文件。")
    lines.append("")
    lines.append("*以上为 DeepSeek 调用失败后的本地兜底摘要。*")
    return "\n".join(lines)


def get_git_versions():
    """获取当前仓库的分支列表和最近提交。"""
    branches_out = run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"])
    current_branch = run_git(["branch", "--show-current"]).strip()
    branches = [line.strip() for line in branches_out.splitlines() if line.strip()]

    commits_out = run_git(
        ["log", "--date=short", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s", "-20"]
    )
    commits = []
    for line in commits_out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, short_sha, date, subject = parts
        commits.append(
            {"sha": sha, "short_sha": short_sha, "date": date, "subject": subject}
        )

    return current_branch, branches, commits


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
    for i, (key, label, _, _) in enumerate(options):
        print(f"  [{key}]  {label}")

    print(f"\n{y}分支：{r}")
    for i, branch in enumerate(branches):
        key = str(i + 1)
        options.append((key, branch, "range", branch))
        print(f"  [{key:>2}]  {branch}")

    print(f"\n{y}最近提交：{r}")
    for j, commit in enumerate(commits):
        key = str(len(branches) + j + 1)
        options.append((key, f"{commit['short_sha']} {commit['date']} {commit['subject']}", "range", commit["sha"]))
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


def generate_report(mode, base, diff_only, output_file, no_color):
    """执行 diff 读取和 AI 生成，返回报告文本。"""
    c = "" if no_color else "\033[36m"
    r = "" if no_color else "\033[0m"
    y = "" if no_color else "\033[33m"
    g = "" if no_color else "\033[32m"

    if not REF_PATTERN.match(base):
        print(f"错误：版本名包含不支持的字符: {base}", file=sys.stderr)
        sys.exit(1)

    try:
        run_git(["rev-parse", "--show-toplevel"])
        stat_args, diff_args = build_diff_args(mode, base)
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

    if diff_only:
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(full_diff + "\n")
            print(f"Diff 已写入 {output_file}", file=sys.stderr)
        else:
            print(full_diff)
        return

    mode_label = {"working": "工作区 vs HEAD", "staged": "暂存区", "range": f"{base}...HEAD"}[mode]
    print(f"{c}范围：{r}{mode_label}　{c}文件：{r}{files_changed}　{c}截断：{r}{'是' if truncated else '否'}", file=sys.stderr)
    print(f"{y}正在调用 DeepSeek 生成周报...{r}", file=sys.stderr)

    try:
        prompt = build_weekly_prompt(full_diff)
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
  workbrief -i                    交互选择 diff 范围
  workbrief                        工作区 vs HEAD
  workbrief -s                     仅暂存区
  workbrief -b main                从 main 到 HEAD
  workbrief -b main -d             只看 diff
  workbrief -l                     列出可用的分支和提交
  workbrief -o weekly.md           输出到文件
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
        default="main",
        help="起始版本 (默认 main)",
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
    else:
        mode = "staged" if args.staged else args.mode
        base = "HEAD" if mode != "range" else args.base

    generate_report(mode, base, args.diff_only, args.output, args.no_color)


if __name__ == "__main__":
    main()
