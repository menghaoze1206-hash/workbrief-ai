#!/usr/bin/env python3
import json
import os
import re
import sys
import subprocess
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


MAX_DIFF_BYTES = 240_000
MAX_PROMPT_CHARS = 16_000
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
CLAUDE_SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/\-]+$")


class WorkBriefHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/git-diff":
            self.handle_git_diff(parsed.query)
            return
        if parsed.path == "/api/git-versions":
            self.handle_git_versions()
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate-weekly":
            self.handle_generate_weekly()
            return
        self.write_json({"error": "接口不存在。"}, status=404)

    def handle_git_versions(self):
        try:
            root = self.run_git(["rev-parse", "--show-toplevel"]).strip()
            current_branch = self.run_git(["branch", "--show-current"]).strip()
            branches = self.get_branches()
            commits = self.get_recent_commits()
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() or error.stdout.strip() or str(error)
            self.write_json({"error": message}, status=400)
            return

        self.write_json(
            {
                "root": root,
                "current_branch": current_branch,
                "branches": branches,
                "commits": commits,
            }
        )

    def handle_generate_weekly(self):
        try:
            payload = self.read_json_body()
            prompt = self.build_weekly_prompt(payload)
            text = self.call_deepseek(prompt)
        except ValueError as error:
            self.write_json({"error": str(error)}, status=400)
            return
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="ignore")
            self.write_json({"error": detail or f"DeepSeek 请求失败：{error.code}"}, status=502)
            return
        except urllib.error.URLError as error:
            self.write_json({"error": f"DeepSeek 网络请求失败：{error.reason}"}, status=502)
            return

        self.write_json({"model": DEEPSEEK_MODEL, "text": text})

    def handle_git_diff(self, query):
        params = parse_qs(query)
        mode = params.get("mode", ["working"])[0]
        base = params.get("base", ["main"])[0] or "main"

        if mode not in {"working", "range", "staged"}:
            self.write_json({"error": "不支持的 diff 范围。"}, status=400)
            return

        if not REF_PATTERN.match(base):
            self.write_json({"error": "Base 分支名包含不支持的字符。"}, status=400)
            return

        try:
            self.run_git(["rev-parse", "--show-toplevel"])
            stat_args, diff_args = self.build_diff_args(mode, base)
            stat = self.run_git(stat_args)
            diff = self.run_git(diff_args, max_bytes=MAX_DIFF_BYTES)
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() or error.stdout.strip() or str(error)
            self.write_json({"error": message}, status=400)
            return

        self.write_json(
            {
                "mode": mode,
                "base": base,
                "stat": stat,
                "diff": f"{stat}\n\n{diff}".strip(),
                "files_changed": self.count_files(stat),
                "truncated": len(diff.encode("utf-8")) >= MAX_DIFF_BYTES,
            }
        )

    def build_diff_args(self, mode, base):
        if mode == "range":
            ref = f"{base}...HEAD"
            return ["diff", "--stat", ref, "--"], ["diff", ref, "--"]
        if mode == "staged":
            return ["diff", "--cached", "--stat", "--"], ["diff", "--cached", "--"]
        return ["diff", "--stat", "HEAD", "--"], ["diff", "HEAD", "--"]

    def get_branches(self):
        output = self.run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"])
        return [line.strip() for line in output.splitlines() if line.strip()]

    def get_recent_commits(self):
        output = self.run_git(
            ["log", "--date=short", "--pretty=format:%H%x1f%h%x1f%ad%x1f%s", "-30"]
        )
        commits = []
        for line in output.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            sha, short_sha, date, subject = parts
            commits.append(
                {
                    "sha": sha,
                    "short_sha": short_sha,
                    "date": date,
                    "subject": subject,
                }
            )
        return commits

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("请求体为空。")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def build_weekly_prompt(self, payload):
        git_diff = str(payload.get("gitDiff", "")).strip()
        if not git_diff:
            raise ValueError("请先读取或粘贴 Git diff。")

        diff_text = git_diff[:MAX_PROMPT_CHARS]
        truncated = "\n[diff 已截断，仅保留前 16000 字符]" if len(git_diff) > MAX_PROMPT_CHARS else ""

        return f”””你是一名擅长写周报的中文助手。你的读者是不懂代码的老板，需要你根据 Git diff 反推本周的工作成果。

要求：
1. 每条用老板能看懂的业务语言描述，禁用技术术语（如 refactor、bugfix、API、组件、模块、依赖等）。
2. 如果 diff 来自某个功能模块，推断这个改动对用户/客户有什么影响，而不是描述改了什么文件。
3. 当实在无法判断业务含义时，用”优化了 XX 相关功能”一笔带过，不要提文件路径或函数名。
4. 输出 3-6 条要点，每条一句话，直接可贴周报。

Git diff：
{diff_text}{truncated}”””

    def call_deepseek(self, prompt):
        api_key = self.get_deepseek_api_key()
        body = json.dumps(
            {
                "model": DEEPSEEK_MODEL,
                "thinking": {"type": "disabled"},
                "messages": [
                    {
                        "role": "system",
                        "content": "你只输出可直接提交的中文周报正文。面向老板，用业务语言，不提技术细节。",
                    },
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

    def get_deepseek_api_key(self):
        key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if key:
            return key.removeprefix("Bearer ").strip()

        try:
            with open(CLAUDE_SETTINGS_PATH, "r", encoding="utf-8") as file:
                settings = json.load(file)
        except FileNotFoundError as error:
            raise ValueError("未找到 Claude Code 配置文件，无法读取 DeepSeek API Key。") from error

        env = settings.get("env", {})
        key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("Claude Code 配置中未找到 ANTHROPIC_AUTH_TOKEN。")
        return key.removeprefix("Bearer ").strip()

    def run_git(self, args, max_bytes=None):
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=self.server.git_cwd,
        )
        output = result.stdout
        if max_bytes and len(output.encode("utf-8")) > max_bytes:
            encoded = output.encode("utf-8")[:max_bytes]
            output = encoded.decode("utf-8", errors="ignore")
            output += "\n\n[diff 已由本地服务截断]"
        return output

    def count_files(self, stat):
        for line in reversed(stat.splitlines()):
            match = re.search(r"(\d+) files? changed", line)
            if match:
                return int(match.group(1))
        return 0

    def write_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    static_dir = os.path.dirname(os.path.abspath(__file__))
    handler = partial(WorkBriefHandler, directory=static_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.git_cwd = os.getcwd()
    print(f"WorkBrief AI running at http://127.0.0.1:{port}")
    print(f"Reading Git diff from: {server.git_cwd}")
    server.serve_forever()


if __name__ == "__main__":
    main()
