# WorkBrief AI

根据 Git diff 生成研发周报的本地工具。

## 功能

- 支持查询 Git 分支和最近提交，并选择从哪个版本开始生成 diff
- 支持读取工作区、暂存区或所选版本到 `HEAD` 的 Git diff
- 根据代码变更生成简洁中文研发周报
- 固定调用 DeepSeek `deepseek-v4-flash` 生成周报
- DeepSeek 调用失败时使用本地模板生成 diff 摘要
- 支持 Markdown 原文和渲染预览两种结果视图
- 支持复制和下载 TXT

## 使用

在目标 Git 仓库目录运行本地服务：

```bash
cd /path/to/your/git-repo
python3 /Users/mhz/code/workbrief-ai/server.py
```

然后打开 `http://127.0.0.1:8000`，选择起始版本，点击“读取 Diff”，再生成周报。

读取范围：

- 工作区相对 `HEAD`
- 仅暂存区
- 所选分支、tag 或 commit 到当前 `HEAD`

生成周报会由本地服务读取 Claude Code 配置中的 API Key，并调用 DeepSeek：

- Base URL：`https://api.deepseek.com`
- 模型：`deepseek-v4-flash`
- 密钥来源：`~/.claude/settings.json` 中的 `env.ANTHROPIC_AUTH_TOKEN`

API Key 不会写入前端页面。正式上线时仍建议通过后端代理和服务端密钥管理转发 AI 调用。
