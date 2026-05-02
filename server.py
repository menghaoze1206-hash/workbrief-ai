#!/usr/bin/env python3
import json
import os
import re
import sys
import subprocess
import urllib.error
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import (
    MAX_DIFF_BYTES,
    REF_PATTERN,
    build_diff_args,
    build_weekly_prompt as core_build_prompt,
    call_deepseek,
    count_files,
    get_deepseek_api_key,
    get_git_versions,
    run_git as core_run_git,
    summarize_diff,
)


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
            current_branch, branches, commits = get_git_versions(cwd=self.server.git_cwd)
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
            text = call_deepseek(prompt)
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

        from core import DEEPSEEK_MODEL
        self.write_json({"model": DEEPSEEK_MODEL, "text": text})

    def handle_git_diff(self, query):
        params = parse_qs(query)
        mode = params.get("mode", ["working"])[0]
        base = params.get("base", ["main"])[0] or "main"
        to = params.get("to", ["HEAD"])[0] or "HEAD"

        if mode not in {"working", "range", "staged"}:
            self.write_json({"error": "不支持的 diff 范围。"}, status=400)
            return

        if not REF_PATTERN.match(base):
            self.write_json({"error": "Base 分支名包含不支持的字符。"}, status=400)
            return

        if mode == "range" and not REF_PATTERN.match(to):
            self.write_json({"error": "to 分支名包含不支持的字符。"}, status=400)
            return

        try:
            self.run_git(["rev-parse", "--show-toplevel"])
            stat_args, diff_args = build_diff_args(mode, base, to=to)
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
                "to": to,
                "stat": stat,
                "diff": f"{stat}\n\n{diff}".strip(),
                "files_changed": count_files(stat),
                "truncated": len(diff.encode("utf-8")) >= MAX_DIFF_BYTES,
            }
        )

    def build_weekly_prompt(self, payload):
        git_diff = str(payload.get("gitDiff", "")).strip()
        if not git_diff:
            raise ValueError("请先读取或粘贴 Git diff。")
        return core_build_prompt(git_diff)

    def run_git(self, args, max_bytes=None):
        return core_run_git(args, max_bytes=max_bytes, cwd=self.server.git_cwd)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("请求体为空。")
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

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
