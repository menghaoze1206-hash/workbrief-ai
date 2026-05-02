# WorkBrief AI

根据 Git diff 生成研发周报的本地工具。

## 一键安装

```bash
git clone https://github.com/menghaoze1206-hash/workbrief-ai.git
cd workbrief-ai && ./install.sh
```

安装后在任意 Git 仓库目录直接使用 `workbrief` 命令。

## CLI 使用

```bash
wk              # 工作区 vs HEAD，生成周报
wk -s           # 仅暂存区
wk -b main      # main...HEAD
wk -d           # 只看 diff，不调 AI
wk -o w.md      # 输出到文件
```

## 浏览器 UI（可选）

```bash
cd /path/to/your/git-repo
python3 /path/to/workbrief-ai/server.py
```

然后打开 `http://127.0.0.1:8000`，选择起始版本生成周报。

## 配置

- Base URL：`https://api.deepseek.com`，模型 `deepseek-v4-flash`
- API Key 读取顺序：`DEEPSEEK_API_KEY` 环境变量 → `ANTHROPIC_AUTH_TOKEN` 环境变量 → `~/.claude/settings.json` 中的 `env.ANTHROPIC_AUTH_TOKEN`
- API Key 不会写入前端页面
