# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

WorkBrief AI — a local tool that reads Git diffs and generates Chinese weekly dev reports via DeepSeek. Three files: `workbrief.py` (CLI), `server.py` + `index.html` (browser UI). No dependencies, no build step.

See `AGENTS.md` for detailed code style, naming conventions, and manual test checklist.

## Commands

**Install (once):**
```bash
./install.sh    # symlinks workbrief.py to a writable bin dir in PATH
```

**CLI (recommended):**
```bash
workbrief                    # working vs HEAD
workbrief -s                 # staged only
workbrief -b main            # main...HEAD
workbrief -d                 # diff only, no AI call
workbrief -o weekly.md       # write to file
```

**Browser UI:**
```bash
python3 server.py              # Start on port 8000 (default)
python3 server.py 3000         # Custom port
PORT=3000 python3 server.py    # Via env var
```

Run from the target Git repo. Both `workbrief.py` and `server.py` read Git state from `os.getcwd()`.

## Architecture

**Core logic** is shared between `workbrief.py` and `server.py` — both contain copies of `run_git()`, `build_diff_args()`, `build_weekly_prompt()`, `call_deepseek()`, `get_deepseek_api_key()`. If you change one, mirror it in the other.

**CLI (`workbrief.py`):**
- argparse-based, outputs to stdout or file via `-o`
- Falls back to `summarize_diff()` (local template) on API failure
- `--diff-only` / `-d` skips the AI call entirely

**Backend (`server.py`):**
- `WorkBriefHandler` extends `SimpleHTTPRequestHandler`, serves static files + 3 API endpoints:
  - `GET /api/git-versions` — lists branches and recent commits via `git for-each-ref` / `git log`
  - `GET /api/git-diff?mode=&base=` — returns `git diff` output (working/staged/range modes), truncated at 240KB
  - `POST /api/generate-weekly` — builds a prompt from the diff and calls DeepSeek API
- API key resolution order: `DEEPSEEK_API_KEY` env → `ANTHROPIC_AUTH_TOKEN` env → `~/.claude/settings.json` `env.ANTHROPIC_AUTH_TOKEN`
- DeepSeek endpoint: `https://api.deepseek.com/chat/completions`, model `deepseek-v4-flash`, thinking disabled
- Prompt is truncated to 16,000 chars before sending
- `run_git()` runs all git commands with a 10s timeout in `server.git_cwd`

**Frontend (`index.html`):**
- Settings persisted to `localStorage` under key `workbrief-diff-settings`
- `summarizeDiff()` provides a local fallback report when the API call fails
- `renderMarkdown()` is a lightweight inline Markdown→HTML renderer (headings, lists, code blocks, bold, inline code)
- Two output views: rendered preview (default) and raw Markdown, plus copy/download

**Key constraints:**
- `MAX_DIFF_BYTES = 240_000`, `MAX_PROMPT_CHARS = 16_000`
- Git ref names validated with `REF_PATTERN = r"^[A-Za-z0-9._/\-]+$"` before shell use
- Diff mode `range` uses `base...HEAD` syntax
