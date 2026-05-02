# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

WorkBrief AI — a local tool that reads Git diffs and generates Chinese weekly dev reports via DeepSeek. Four files: `core.py` (shared logic), `wk.py` (CLI), `server.py` + `index.html` (browser UI). No dependencies, no build step.

See `AGENTS.md` for detailed code style, naming conventions, and manual test checklist.

## Commands

**Install (once):**
```bash
./install.sh    # symlinks wk.py to a writable bin dir in PATH
```

**CLI (recommended):**
```bash
workbrief                    # working vs HEAD
wk -s                 # staged only
wk -b main            # main...HEAD (range mode)
wk -b v1.0 -t v2.0    # v1.0...v2.0
wk -i                 # interactive version picker
wk -l                 # list branches and recent commits
wk -d                 # diff only, no AI call
wk --dry              # preview prompt without calling API
wk -o weekly.md       # write to file
```

**Browser UI:**
```bash
python3 server.py              # Start on port 8000 (default)
python3 server.py 3000         # Custom port
PORT=3000 python3 server.py    # Via env var
```

Run from the target Git repo. Both `wk.py` and `server.py` read Git state from `os.getcwd()`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | — | API key (highest priority) |
| `ANTHROPIC_AUTH_TOKEN` | — | Fallback API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API base URL |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | Model name |
| `DEEPSEEK_TEMPERATURE` | `0.35` | Generation temperature |

API key also falls back to `~/.claude/settings.json` → `env.ANTHROPIC_AUTH_TOKEN`.

## Architecture

**`core.py` — shared logic (single source of truth):**
- `run_git(args, max_bytes, cwd)` — all git commands, optional working directory
- `build_diff_args(mode, base, to="HEAD")` — builds git diff argument lists
- `build_weekly_prompt(git_diff)` — constructs the Chinese prompt for DeepSeek
- `call_deepseek(prompt)` — sends the API request
- `get_deepseek_api_key()` — resolves API key from env or Claude Code settings
- `summarize_diff(diff)` — local fallback template on API failure
- `get_git_versions(cwd)` — returns (current_branch, branches, commits)
- `count_files(stat)` — parses file count from `git diff --stat` output

Both `wk.py` and `server.py` import from `core.py`. Never duplicate logic between them.

**CLI (`wk.py`):**
- argparse-based, outputs to stdout or file via `-o`
- `-i` launches an interactive numbered menu of branches and commits
- `--dry` prints the prompt without calling the API
- Falls back to `summarize_diff()` on API failure

**Backend (`server.py`):**
- `WorkBriefHandler` extends `SimpleHTTPRequestHandler`, serves static files + 3 API endpoints:
  - `GET /api/git-versions` — lists branches and recent commits
  - `GET /api/git-diff?mode=&base=&to=` — returns `git diff` output (working/staged/range modes), truncated at 240KB
  - `POST /api/generate-weekly` — builds a prompt from the diff and calls DeepSeek API
- `run_git()` is a thin wrapper around `core.run_git()` that passes `cwd=self.server.git_cwd`
- Prompt is truncated to 16,000 chars before sending

**Frontend (`index.html`):**
- Settings persisted to `localStorage` under key `workbrief-diff-settings`
- `summarizeDiff()` provides a local fallback report when the API call fails
- `renderMarkdown()` is a lightweight inline Markdown→HTML renderer (headings, lists, code blocks, bold, inline code)
- Two output views: rendered preview (default) and raw Markdown, plus copy/download

**Key constraints:**
- `MAX_DIFF_BYTES = 240_000`, `MAX_PROMPT_CHARS = 16_000`
- Git ref names validated with `REF_PATTERN` before shell use
