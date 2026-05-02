"""WorkBrief AI — 共享核心逻辑，供 CLI 和 server 共用。"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

MAX_DIFF_BYTES = 240_000
MAX_PROMPT_CHARS = 16_000
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TEMPERATURE = float(os.environ.get("DEEPSEEK_TEMPERATURE", "0.35"))
CLAUDE_SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/\-]+$")


def run_git(args, max_bytes=None, cwd=None):
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=cwd,
    )
    output = result.stdout
    if max_bytes and len(output.encode("utf-8")) > max_bytes:
        encoded = output.encode("utf-8")[:max_bytes]
        output = encoded.decode("utf-8", errors="ignore")
        output += "\n\n[diff 已截断]"
    return output


def build_diff_args(mode, base, to="HEAD"):
    if mode == "range":
        ref = f"{base}...{to}"
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
            "temperature": DEEPSEEK_TEMPERATURE,
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


def get_git_versions(cwd=None):
    branches_out = run_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=cwd
    )
    current_branch = run_git(["branch", "--show-current"], cwd=cwd).strip()
    branches = [line.strip() for line in branches_out.splitlines() if line.strip()]

    commits_out = run_git(
        ["log", "--date=short", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s", "-20"],
        cwd=cwd,
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
