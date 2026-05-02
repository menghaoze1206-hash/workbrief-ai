# 仓库指南

## 项目结构与模块组织

本仓库是 **WorkBrief AI** 的轻量级本地工具，用于根据 Git diff 生成中文研发周报。

- `core.py` 包含所有共享核心逻辑（`run_git`、`build_diff_args`、`build_weekly_prompt`、`call_deepseek`、`get_deepseek_api_key`、`summarize_diff`、`get_git_versions`），`wk.py` 和 `server.py` 均从 `core` import。
- `wk.py` 是 CLI 版本，推荐使用。
- `server.py` 提供本地静态服务和 API 接口（`/api/git-versions`、`/api/git-diff`、`/api/generate-weekly`）。
- `index.html` 包含完整浏览器 UI：HTML 结构、内联 CSS 和内联 JavaScript。
- `README.md` 说明产品功能和浏览器使用方式。
- 当前没有 `src/`、`tests/`、包管理配置、构建流程或资源目录。

保持改动聚焦。若应用继续增长，可将可复用 JavaScript 拆到 `src/`，将静态资源放到 `assets/`，但不要在没有明确需求时引入框架。

所有核心逻辑集中在 `core.py`，`wk.py` 和 `server.py` 都从 `core` import。不要在 `wk.py` 或 `server.py` 中重复实现 `core.py` 已有的函数。新增共享逻辑优先放在 `core.py`。

## 构建、测试与本地开发命令

本项目不需要安装依赖或构建步骤。

CLI:
- 生成周报：`python3 wk.py`
- 暂存区：`python3 wk.py -s`
- 范围 diff：`python3 wk.py -b main`
- 仅输出 diff：`python3 wk.py -d`
- 输出到文件：`python3 wk.py -o weekly.md`

浏览器 UI:
- 本地打开：`open index.html`
- 启动带 Git diff 接口的本地服务：`python3 server.py`
- 访问地址：`http://localhost:8000`
- 在其他 Git 仓库生成周报：`cd /path/to/repo && python3 /Users/mhz/code/workbrief-ai/server.py`

除非新增包管理配置，否则不要引入 `npm test`、`npm run build` 等命令。

## 代码风格与命名约定

沿用当前单文件风格：

- HTML 使用语义化区块和清晰的 `id` 属性。
- CSS 使用 `:root` 自定义变量、类选择器、2 空格缩进和紧凑的响应式媒体查询。
- JavaScript 使用 `const`/`let`、小型命名函数、camelCase 标识符，以及现有 `$()` DOM 辅助函数。
- 界面文案以简体中文为主，新增文案应围绕代码变更、研发周报和职场汇报场景。

避免无关的格式化改动。仅在逻辑不明显时添加简短注释。

## 测试指南

当前没有自动化测试。提交改动前请在浏览器中手动验证：

- 读取或手动粘贴 Git diff。
- 查询分支和最近提交，并选择起始版本。
- 生成、重新生成、Markdown 预览、清空、复制和下载 TXT。
- 通过本地服务读取工作区、暂存区和 `base...HEAD` diff。
- 未启用 AI API 时的本地模板生成。
- 凭据缺失或接口请求失败时的 API 回退行为。
- 桌面、平板和移动端宽度下的响应式布局。

如后续添加测试，优先使用聚焦的浏览器或 DOM 测试，并按行为命名，例如 `report-generation.test.js`。

## 提交与 Pull Request 规范

当前目录不是 Git 仓库，因此没有可参考的项目提交历史。提交信息应简洁、使用祈使句，例如 `Add API fallback warning`。

Pull Request 应包含：

- 面向用户的变更摘要。
- 手动测试说明，包括浏览器和视口覆盖情况。
- 视觉改动的截图。
- 安全影响说明，尤其是涉及 API Key、浏览器存储或 API 调用的改动。

## 安全与配置提示

应用由本地 `server.py` 读取 Claude Code 配置中的 `env.ANTHROPIC_AUTH_TOKEN`，并调用 DeepSeek `deepseek-v4-flash`。不要把 API Key 写入前端文件、日志或文档；生产环境应改用正式的服务端密钥管理。
