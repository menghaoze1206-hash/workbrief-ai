# WorkBrief AI

根据 Git diff 生成研发周报的本地工具，输出面向老板的业务语言周报。

## 一键安装

```bash
git clone git@github.com:menghaoze1206-hash/workbrief-ai.git
cd workbrief-ai && ./install.sh
```

安装后在任意 Git 仓库目录直接使用 `wk` 命令。

卸载：`./uninstall.sh`

## CLI 使用

```bash
wk                  # 工作区 vs HEAD，生成周报
wk -s               # 仅暂存区
wk -b main          # main...HEAD
wk -b v1.0 -t v2.0  # v1.0...v2.0
wk -i               # 交互式选择 diff 范围
wk -l               # 列出可用的分支和最近提交
wk -d               # 只看 diff，不调 AI
wk --dry            # 预览 prompt，不调 API
wk -o weekly.md     # 输出到文件
wk --help           # 查看所有参数
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | — | API Key（优先级最高） |
| `ANTHROPIC_AUTH_TOKEN` | — | 备用 API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `DEEPSEEK_TEMPERATURE` | `0.35` | 生成温度 |

API Key 读取顺序：`DEEPSEEK_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → `~/.claude/settings.json`

## 切换模型示例

```bash
# 用阿里云百炼的 GLM 5.1
DEEPSEEK_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
DEEPSEEK_MODEL=glm-5.1 \
DEEPSEEK_API_KEY=你的key \
wk

# 用小米 MiMo
DEEPSEEK_BASE_URL=https://api.xiaomi.com/v1 \
DEEPSEEK_MODEL=mimo-v2-pro \
wk
```

## 浏览器 UI（可选）

```bash
cd /path/to/your/git-repo
python3 /path/to/workbrief-ai/server.py
```

打开 `http://127.0.0.1:8000`。

## 项目结构

```
workbrief-ai/
├── core.py          # 共享核心逻辑（Git/DeepSeek）
├── wk.py            # CLI 入口
├── __main__.py      # python3 workbrief-ai/ 入口
├── server.py        # 浏览器 UI 后端
├── index.html       # 浏览器 UI 前端
├── install.sh       # 一键安装
└── uninstall.sh     # 卸载
```
