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
    return f"""你是一名擅长研发周报写作的中文助手。请根据 Git diff 生成一份简洁的中文研发周报。

要求：
1. 只基于 diff 总结，不要编造不存在的功能、数字或业务结果。
2. 重点是"本周改了什么"，不要逐行解释代码，也不要展开太细。
3. 输出 3-6 条要点即可，每条一句话，适合直接贴到周报里。
4. 如果能判断业务含义，就用业务口径表达；判断不了时，用模块/文件变更口径表达。
5. 不需要单独写风险、下周计划、技术细节长段落。

Git diff：
{diff_text}{truncated}"""


def call_deepseek(prompt):
    api_key = get_deepseek_api_key()
    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": "你只输出可直接提交的中文研发周报正文。"},
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
        "## 研发周报（本地模板）",
        "",
        f"- 本周完成了一批代码变更，涉及 {len(files) or '若干'} 个文件，新增 {additions} 行、删除 {deletions} 行。",
    ]
    for f in file_list:
        lines.append(f"- 调整了 `{f}` 相关逻辑。")
    if len(files) > 8:
        lines.append(f"- ... 以及其他 {len(files) - 8} 个文件。")
    lines.append("")
    lines.append("*以上为 DeepSeek 调用失败后的本地兜底摘要，建议结合实际业务背景再做微调。*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="根据 Git diff 生成中文研发周报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  workbrief                         工作区相对 HEAD 生成周报
  workbrief --staged                仅暂存区
  workbrief --base main             从 main 到 HEAD
  workbrief --base v1.0 --diff-only 只输出 v1.0...HEAD 的 diff
  workbrief -o weekly.md            输出到文件
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
        help="起始版本，仅 range 模式有效 (默认 main)",
    )
    parser.add_argument(
        "--staged", "-s",
        action="store_true",
        help="等同于 --mode staged",
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

    mode = "staged" if args.staged else args.mode
    base = args.base
    if mode != "range":
        base = "HEAD"

    # Validate base ref
    if not REF_PATTERN.match(base):
        print(f"错误：base 分支名包含不支持的字符: {base}", file=sys.stderr)
        sys.exit(1)

    # Read diff
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

    if args.diff_only:
        output = full_diff
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output + "\n")
            print(f"Diff 已写入 {args.output}", file=sys.stderr)
        else:
            print(output)
        return

    # Summary line
    c = "\033[36m" if not args.no_color else ""
    r = "\033[0m" if not args.no_color else ""
    y = "\033[33m" if not args.no_color else ""
    g = "\033[32m" if not args.no_color else ""

    mode_label = {"working": "工作区 vs HEAD", "staged": "暂存区", "range": f"{base}...HEAD"}[mode]
    print(f"{c}范围：{r}{mode_label}　{c}文件：{r}{files_changed}　{c}截断：{r}{'是' if truncated else '否'}", file=sys.stderr)
    print(f"{y}正在调用 DeepSeek 生成周报...{r}", file=sys.stderr)

    # Generate
    try:
        prompt = build_weekly_prompt(full_diff)
        report = call_deepseek(prompt)
    except (ValueError, urllib.error.HTTPError, urllib.error.URLError) as e:
        msg = str(e)
        if hasattr(e, "read"):
            msg = e.read().decode("utf-8", errors="ignore")[:200]
        print(f"{y}DeepSeek 调用失败，使用本地模板：{msg}{r}", file=sys.stderr)
        report = summarize_diff(full_diff)
    else:
        if not report:
            print(f"{y}DeepSeek 返回空内容，使用本地模板。{r}", file=sys.stderr)
            report = summarize_diff(full_diff)
        else:
            print(f"{g}生成完成。{r}", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"周报已写入 {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
