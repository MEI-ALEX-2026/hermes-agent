# Hermes Agent Dashboard 与 TUI 快速掌握教程

更新时间：2026-05-27
适用范围：当前仓库的 Web Dashboard、嵌入式 Chat 页、`hermes --tui` 终端界面。

这份文档的目标是让你快速知道：

- Dashboard 每个页面是干什么的。
- 哪些操作会改配置、密钥、会话、插件或定时任务。
- TUI 里常用 slash 命令怎么用。
- 日常使用时应该按什么路径排查问题和推进工作。

## 1. 启动方式

### 启动普通 Dashboard

```bash
hermes dashboard
```

默认打开本机 `http://127.0.0.1:9119`。普通模式不显示浏览器内的 Chat 页。

常用参数：

| 参数 | 用途 |
| --- | --- |
| `--port 8080` | 改端口。 |
| `--host 127.0.0.1` | 指定监听地址。默认只绑定本机。 |
| `--no-open` | 启动服务但不自动打开浏览器。 |
| `--tui` | 开启 Dashboard 内嵌 Chat 页，也就是浏览器里的真实 TUI。 |
| `--insecure` | 允许绑定非本机地址。谨慎使用，因为 Dashboard 能读写密钥。 |

### 启动带 Chat 页的 Dashboard

```bash
hermes dashboard --tui
```

`/chat` 页不是 React 重写的聊天界面，而是通过 PTY/WebSocket 嵌入真实的 `hermes --tui`。因此终端 TUI 能做的事，浏览器 Chat 页基本也能做：slash 命令、模型切换、工具调用进度、审批、澄清、复制等。

### 单独启动 TUI

```bash
hermes --tui
```

适合长期开发、编码、调试和连续对话。Dashboard 的 `/chat` 适合想同时看会话、日志、模型和配置时使用。

## 2. Dashboard 总览

Dashboard 左侧是主导航。当前内置页面包括：

| 页面 | 用途 |
| --- | --- |
| Chat | 浏览器内嵌 TUI。仅 `hermes dashboard --tui` 或 `HERMES_DASHBOARD_TUI=1` 时显示。 |
| Sessions | 浏览、搜索、恢复、删除历史会话。当前默认首页会跳到这里。 |
| Analytics | 查看 Token、成本、模型、技能使用统计。是否显示在侧边栏受 `dashboard.show_token_analytics` 控制。 |
| Models | 查看模型用量、成本、能力标签，并把模型设为主模型或辅助任务模型。 |
| Logs | 查看 `agent.log`、`errors.log`、`gateway.log`，支持过滤和自动刷新。 |
| Cron | 创建和管理定时任务，让 Agent 按计划执行 prompt。 |
| Skills | 查看、搜索、启用/禁用技能和工具集。 |
| Plugins | 安装、启用、更新、移除插件，配置记忆提供方和上下文引擎。 |
| Profiles | 管理多 Agent 配置，包括创建 profile、改名、编辑 SOUL.md。 |
| Config | 表单或 YAML 模式编辑 `~/.hermes/config.yaml`。 |
| Keys | 管理 `~/.hermes/.env` 中的 API key、OAuth 登录和消息平台凭据。 |
| Documentation | 在 Dashboard 内查看文档页面。 |

左侧 System 区域还有两个全局操作：

| 操作 | 用途 |
| --- | --- |
| Restart Gateway | 重启消息网关。改了 gateway 相关配置、平台 token 或遇到网关异常时用。 |
| Update Hermes | 执行 Hermes 更新流程。会进入更新状态，适合从 UI 触发升级。 |

底部还有：

- Gateway 状态和活跃会话数：点击会跳到 Sessions。
- 主题切换：切换 Dashboard 主题，写入 `dashboard.theme`。
- 语言切换：切换 Dashboard UI 语言。
- 版本号：来自当前 Hermes 运行状态。

## 3. Chat 页面

Chat 页用于直接和 Hermes 对话。它的核心区域是 xterm.js 渲染的 TUI 终端。

主要功能：

- 输入自然语言任务。
- 输入 `/help` 查看当前可用命令。
- 使用 `/model` 切换本会话模型。
- 使用 `/resume` 或从 Sessions 页跳转恢复历史会话。
- 处理危险命令审批、澄清问题、密钥输入、sudo 输入等交互。
- 使用右下角 `copy last response` 复制最近一次助手回答。
- 右侧 Model/Tools 面板显示当前模型、连接状态和最近工具调用。

右侧面板：

| 区块 | 用途 |
| --- | --- |
| model | 显示当前模型，点击可打开模型选择器。 |
| live/connecting/error 状态 | 表示 Dashboard sidecar WebSocket 是否正常。 |
| tools | 显示最近工具调用，包含运行中、完成、错误、摘要和 inline diff。 |
| reconnect | 事件流或 sidecar 出错时重新连接，不会影响左侧终端里的主 TUI。 |

从 Sessions 页点击“继续/播放”会跳到：

```text
/chat?resume=<session_id>
```

Chat 页会用 TUI 恢复该会话历史。

## 4. Sessions 页面

Sessions 是历史会话中心。

能做什么：

- 查看每个会话的标题、来源平台、模型、消息数、工具调用数、最近活动时间。
- 搜索全部会话内容，后端使用 FTS5。
- 展开会话查看完整消息历史。
- 按角色区分 user、assistant、system、tool 消息。
- Markdown 渲染助手回答。
- 展开工具调用块查看函数名和 JSON 参数。
- 删除会话。
- 在启用 Chat 页时，直接恢复会话到浏览器 TUI。

常见用法：

- 找旧结论：在搜索框输入关键词。
- 继续旧任务：找到会话后点恢复。
- 清理无用历史：删除测试会话或错误会话。

## 5. Analytics 页面

Analytics 用于看总体使用趋势。

时间范围：

- `7d`
- `30d`
- `90d`

主要指标：

- 总 Token 数。
- 总会话数。
- API 调用次数。
- 每日 Token 用量柱状图。
- 每日明细表。
- 按模型拆分的使用统计。
- 常用技能统计。

如果侧边栏不显示 Analytics，检查：

```yaml
dashboard:
  show_token_analytics: true
```

## 6. Models 页面

Models 用于理解模型使用和分配模型。

能看到：

- 使用过的模型数量。
- 预估费用。
- Token 使用量。
- 会话数、平均每会话用量、API 调用和工具调用。
- 模型能力标签，例如 Tools、Vision、Reasoning、模型家族。
- Cache Read、Reasoning、Input、Output 的 Token 组成。

重要操作：

- `Use as Main model`：把某个 provider/model 设为主模型。
- `Use as Auxiliary`：把模型分配给辅助任务，例如 Vision、Web Extract、Compression、Skills Hub、Approval、MCP、Title Gen、Kanban 等。
- 打开模型选择器：用于从可用 provider/model 中选择。

适合用来做两类决策：

- 成本排查：哪个模型最耗 Token 或费用。
- 路由优化：给视觉、压缩、标题生成等辅助任务分配更合适的模型。

## 7. Logs 页面

Logs 是本地日志查看器。

可选文件：

- `agent`
- `errors`
- `gateway`

过滤项：

- Level：`ALL`、`DEBUG`、`INFO`、`WARNING`、`ERROR`
- Component：`all`、`gateway`、`agent`、`tools`、`cli`、`cron`
- Lines：`50`、`100`、`200`、`500`
- Auto-refresh：每 5 秒刷新一次

颜色含义：

- 红色：ERROR、CRITICAL、FATAL
- 黄色：WARNING、WARN
- 暗色：DEBUG
- 普通色：INFO 或其他

常见排查路径：

1. Agent 没响应：先看 `agent.log`。
2. 消息平台收不到消息：看 `gateway.log`。
3. 命令或服务报错：看 `errors.log`。
4. 定时任务异常：筛选 Component 为 `cron`。

## 8. Cron 页面

Cron 用于创建和管理定时 Agent 任务。

创建任务需要：

| 字段 | 用途 |
| --- | --- |
| Profile | 指定用哪个多 Agent 配置运行。 |
| Name | 可选名称，方便识别任务。 |
| Prompt | 每次触发时 Agent 要执行的任务。 |
| Schedule | cron 表达式，例如 `0 9 * * *`。 |
| Deliver To | 投递位置：local、Telegram、Discord、Slack、Email。 |

任务列表显示：

- 任务名或 prompt 预览。
- 状态：scheduled、paused、error 等。
- 所属 profile。
- 投递目标。
- 调度表达式。
- 上次运行时间。
- 下次运行时间。
- 最近错误。

操作：

- Pause/Resume：暂停或恢复任务。
- Trigger Now：立即运行一次。
- Delete：删除任务。

典型用法：

- 每日总结。
- 定期检查仓库状态。
- 定时生成报告。
- 给 Telegram/Discord/Slack 推送周期任务结果。

## 9. Skills 页面

Skills 用于管理 Agent 能力。

有两个视图：

| 视图 | 用途 |
| --- | --- |
| Skills | 查看和启用/禁用具体技能。 |
| Toolsets | 查看内置工具集、是否启用、需要的配置和包含的工具。 |

Skills 支持：

- 按名称、描述、分类搜索。
- 按分类过滤。
- 显示已启用数量。
- 切换单个技能启用状态。
- 查看技能是否需要配置。

Toolsets 支持：

- 搜索工具集。
- 查看工具集说明。
- 查看 included tools。
- 判断工具集是否因缺少环境变量或依赖而不可用。

注意：技能启用状态通常对后续新会话生效。当前运行中的会话如果需要重新扫描技能，可以在 TUI 使用 `/reload-skills`。

## 10. Plugins 页面

Plugins 管理 Hermes 插件生态。

主要区块：

| 区块 | 用途 |
| --- | --- |
| Runtime providers | 设置记忆提供方 `memory.provider` 和上下文引擎 `context.engine`。 |
| Install from GitHub / Git | 从 `owner/repo`、HTTPS Git URL 或 SSH Git URL 安装插件。 |
| Installed plugins | 查看已安装插件、运行时状态、来源、版本、Dashboard tab 状态。 |
| Dashboard-only extensions | 只提供 Dashboard 扩展但没有匹配 agent plugin.yaml 的扩展。 |

常用操作：

- 安装插件。
- 强制重装。
- 安装后启用。
- 启用/禁用运行时插件。
- `git pull` 更新用户安装的插件。
- 移除用户安装在 `~/.hermes/plugins/` 下的插件。
- 重新扫描 Dashboard 扩展。
- 显示/隐藏插件侧边栏入口。

插件可能提供：

- 新工具。
- lifecycle hooks。
- CLI 子命令。
- Dashboard 页面。
- Dashboard 插槽内容。
- 插件专属 API 路由。

## 11. Profiles 页面

Profiles 是多 Agent 配置管理页。

一个 profile 有自己的：

- 配置。
- 密钥。
- 记忆。
- 会话。
- 技能。
- 定时任务。
- `SOUL.md` 人格/系统提示词。

页面能力：

- 新建 profile。
- 可选择从 default profile 克隆配置。
- 重命名 profile。
- 编辑 `SOUL.md`。
- 保存 SOUL。
- 复制启动该 profile 的 CLI 命令。
- 删除 profile。

命名规则：

- 仅允许小写字母、数字、下划线、短横线。
- 首字符必须是字母或数字。
- 最多 64 个字符。

典型用法：

- `coder`：偏代码实现。
- `writer`：偏文档和内容。
- `ops`：偏部署、日志、监控。
- `research`：偏检索和分析。

## 12. Config 页面

Config 是 `~/.hermes/config.yaml` 编辑器。

两种模式：

| 模式 | 用途 |
| --- | --- |
| Form | 按 schema 自动生成表单，适合日常编辑。 |
| Raw YAML | 直接编辑 YAML，适合批量修改或复制配置。 |

Form 模式支持：

- 分类浏览。
- 搜索字段名、描述、分类。
- 自动控件：开关、下拉、文本框等。
- 按当前分类或搜索结果恢复默认值。
- 保存到 config.yaml。
- 导出 JSON。
- 导入 JSON。

常见分类：

- agent
- terminal
- display
- delegation
- memory
- compression
- security
- browser
- voice
- tts
- stt
- logging
- discord
- auxiliary
- kanban
- updates

注意：

- 大部分配置对新会话生效。
- gateway 相关配置通常需要重启 gateway。
- 当前运行中的 TUI 会话有些设置可以通过 slash 命令即时更新，例如 `/model`、`/fast`、`/reasoning`、`/verbose`、`/tools enable|disable`。

## 13. Keys 页面

Keys 管理 `~/.hermes/.env` 中的密钥和凭据。

主要能力：

- 按 provider 分组显示 API key。
- 显示已配置数量。
- 设置、替换、清除密钥。
- 显示脱敏预览。
- 点击眼睛图标临时显示真实值。
- 提供获取 key 的外部链接。
- 显示哪些工具依赖该变量。
- OAuth provider 登录。
- 展开高级/罕见变量。

常见分组：

- Nous Portal
- Anthropic
- DashScope/Qwen
- DeepSeek
- Gemini
- GLM/Z.AI
- Hugging Face
- Kimi/Moonshot
- MiniMax
- OpenRouter
- 消息平台 token
- 工具类 API key

安全提醒：

- Dashboard 能读写密钥。
- 默认绑定 `127.0.0.1` 是安全边界的一部分。
- 不要随意用 `--host 0.0.0.0 --insecure` 暴露到局域网。
- 在活跃 TUI 里改了 `.env` 后，用 `/reload` 让运行中的进程重新读取。

## 14. Documentation 页面

Documentation 用于在 Dashboard 内查看文档。它适合在不离开管理面板的情况下查功能说明。

如果你需要源码级理解，优先看：

- `AGENTS.md`
- `website/docs/`
- `hermes_cli/web_server.py`
- `web/src/pages/`
- `ui-tui/src/app/slash/`
- `hermes_cli/commands.py`

## 15. Dashboard 插件扩展点

Dashboard 不是封闭 UI。插件可以：

- 增加侧边栏页面。
- 覆盖内置页面。
- 隐藏自己的 tab。
- 注入 Dashboard shell 插槽。
- 提供 Dashboard 专属静态资源。
- 提供插件 API。

常见插槽名包括：

- `backdrop`
- `header-banner`
- `header-left`
- `header-right`
- `pre-main`
- `post-main`
- `overlay`
- `chat:top`
- `chat:bottom`
- `sessions:top`
- `logs:top`
- `logs:bottom`
- `cron:top`
- `cron:bottom`
- `skills:top`
- `plugins:top`
- `config:top`

是否显示插件 tab 可在 Plugins 页面控制，结果写入：

```yaml
dashboard:
  hidden_plugins:
    - plugin_name
```

## 16. TUI 基础操作

TUI 是 Hermes 的主交互界面。你可以直接输入自然语言，也可以输入 slash 命令。

常用快捷键：

| 快捷键 | 用途 |
| --- | --- |
| `Cmd+C` macOS | 复制选择内容。 |
| `Ctrl+C` | 中断、清草稿、退出；在部分远程终端也可复制选择。 |
| `Cmd+D` / `Ctrl+D` | 退出。 |
| `Cmd+G` / `Ctrl+G` / `Alt+G` | 打开 `$EDITOR` 编辑长输入。 |
| `Cmd+L` / `Ctrl+L` | 重绘界面。 |
| `Cmd+V` macOS / `Alt+V` 其他 | 粘贴文本；`/paste` 用于贴剪贴板图片。 |
| `Tab` | 应用补全。 |
| `↑/↓` | 命令补全、队列编辑、历史输入。 |
| `Ctrl+X` | 删除正在编辑的队列消息。 |
| `Cmd+A/E` / `Ctrl+A/E` | 到行首/行尾。 |
| `Cmd+Z/Y` / `Ctrl+Z/Y` | 输入框撤销/重做。 |
| `Cmd+W` / `Ctrl+W` | 删除一个词。 |
| `Cmd+U/K` / `Ctrl+U/K` | 删除到行首/行尾。 |
| `Cmd+←/→` / `Ctrl+←/→` | 按词跳转。 |
| `Shift+Enter` / `Alt+Enter` | 输入换行。 |
| `\+Enter` | 多行续行 fallback。 |
| `!<cmd>` | 执行 shell 命令，例如 `!git status`。 |
| `{!<cmd>}` | 把 shell 输出插入 prompt，例如 `当前分支是 {!git branch --show-current}`。 |

## 17. TUI 命令模型

TUI 命令有两类：

| 类型 | 说明 |
| --- | --- |
| TUI 原生命令 | 由 `ui-tui/src/app/slash/` 直接处理，能即时操作当前 TUI 状态。 |
| CLI fallback 命令 | TUI 通过 `slash.exec` 交给 Python 侧 `HermesCLI` 处理，和普通 CLI slash 命令保持一致。 |

所以：

- `/help` 会显示当前实际可用命令和快捷键。
- 有些命令在 TUI 中是原生实现，例如 `/model`、`/resume`、`/copy`、`/tools enable`。
- 有些复杂管理命令会交给 CLI worker，例如部分 `/skills`、`/tools`、`/kanban`、`/cron` 子命令。
- Gateway-only 命令主要用于 Telegram/Discord/Slack 等消息平台，不是日常 TUI 主路径。

## 18. TUI 会话命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/help` | 查看命令和快捷键。 | `/help` |
| `/clear` | 清空当前对话并开启新会话。别名：`/new`。 | `/clear` |
| `/new [name]` | 开启带标题的新会话。 | `/new fix-login-bug` |
| `/resume [id/title]` | 恢复历史会话。不带参数打开会话选择器。 | `/resume` |
| `/sessions [id/title]` | 浏览并恢复历史会话。 | `/sessions` |
| `/status` | 查看当前会话状态。 | `/status` |
| `/title [name]` | 查看或设置当前会话标题。 | `/title docs pass` |
| `/history [chars]` | 查看当前 transcript 中 user/assistant 消息。 | `/history 800` |
| `/save` | 保存当前会话到 JSON。 | `/save` |
| `/retry` | 重试上一条用户消息。 | `/retry` |
| `/undo` | 撤销最近一轮 user/assistant 交换。 | `/undo` |
| `/branch [name]` | 从当前会话分叉。别名：`/fork`。 | `/branch alt-solution` |
| `/compress [focus]` | 手动压缩上下文。 | `/compress keep API decisions` |
| `/queue <prompt>` | 排队下一条消息，不中断当前运行。别名：`/q`。 | `/queue 继续写测试` |
| `/steer <prompt>` | 在下一个工具调用后注入引导，不强行中断。 | `/steer 优先检查配置文件` |
| `/background <prompt>` | 后台运行一个 prompt。别名：`/bg`、`/btw`。 | `/bg summarize sessions` |
| `/stop` | 停止后台进程。 | `/stop` |
| `/quit` | 退出 TUI。别名：`/exit`。 | `/quit` |

## 19. TUI 模型与运行模式命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/model` | 打开模型选择器。 | `/model` |
| `/model <model>` | 切换当前会话模型。 | `/model anthropic/claude-sonnet-4` |
| `/personality <name>` | 切换当前会话人格。 | `/personality coder` |
| `/reasoning` | 查看推理设置。 | `/reasoning` |
| `/reasoning <level>` | 设置推理 effort。常见值：`none`、`minimal`、`low`、`medium`、`high`、`xhigh`。 | `/reasoning high` |
| `/reasoning show` | 展开显示 reasoning。 | `/reasoning show` |
| `/reasoning hide` | 隐藏 reasoning。 | `/reasoning hide` |
| `/fast` | 查看 fast mode。 | `/fast` |
| `/fast fast` | 启用 fast/priority 模式。 | `/fast fast` |
| `/fast normal` | 回到普通模式。 | `/fast normal` |
| `/yolo` | 切换本会话跳过危险操作审批。慎用。 | `/yolo` |
| `/verbose [mode]` | 切换工具输出详细程度。 | `/verbose` |
| `/usage` | 查看当前会话 Token、API 调用和成本。 | `/usage` |

## 20. TUI 显示与交互命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/redraw` | 强制重绘界面。 | `/redraw` |
| `/statusbar [on/off/top/bottom/toggle]` | 控制状态栏位置。别名：`/sb`。 | `/statusbar bottom` |
| `/compact [on/off/toggle]` | 切换紧凑 transcript。 | `/compact on` |
| `/details [hidden/collapsed/expanded/cycle]` | 全局控制思考、工具、子代理等详情可见性。 | `/details expanded` |
| `/details <section> <mode>` | 单独控制某类详情。section 包括 `thinking`、`tools`、`subagents`、`activity`。 | `/details tools expanded` |
| `/skin [name]` | 查看或切换 CLI/TUI skin。 | `/skin mono` |
| `/indicator [kaomoji/emoji/unicode/ascii]` | 设置忙碌指示器样式。 | `/indicator unicode` |
| `/mouse [on/off/wheel/buttons/all]` | 设置鼠标追踪模式。别名：`/scroll`。 | `/mouse wheel` |
| `/copy [number]` | 复制选择内容或第 N 条助手回复。不带参数复制最近助手回复。 | `/copy` |
| `/paste` | 附加剪贴板图片。 | `/paste` |
| `/image <path>` | 附加本地图片到下一条 prompt。 | `/image /tmp/screen.png` |
| `/terminal-setup [auto/vscode/cursor/windsurf]` | 配置 IDE 终端多行、撤销/重做快捷键。 | `/terminal-setup cursor` |
| `/fortune [random/daily]` | 显示本地 fortune。 | `/fortune daily` |
| `/logs [n]` | 查看 TUI gateway 日志尾部。 | `/logs 50` |

## 21. TUI 工具、技能、浏览器与 MCP 命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/tools` | 查看工具/工具集状态。 | `/tools` |
| `/tools enable <name>` | 启用工具集或 MCP 工具。 | `/tools enable web` |
| `/tools disable <name>` | 禁用工具集或 MCP 工具。 | `/tools disable browser` |
| `/toolsets` | 列出可用工具集。 | `/toolsets` |
| `/skills` | 打开 TUI Skills Hub。 | `/skills` |
| `/skills list` | 列出已安装技能。 | `/skills list` |
| `/skills inspect <name>` | 查看技能详情。 | `/skills inspect git-essentials` |
| `/skills search <query>` | 搜索技能。 | `/skills search android` |
| `/skills browse [page]` | 浏览社区技能。 | `/skills browse 2` |
| `/skills install <name/url>` | 安装技能。 | `/skills install owner/repo` |
| `/reload-skills` | 重新扫描 `~/.hermes/skills/`。别名：`/reload_skills`。 | `/reload-skills` |
| `/reload` | 重新读取 `~/.hermes/.env` 到当前进程。 | `/reload` |
| `/reload-mcp [now/always]` | 重新加载 MCP server。别名：`/reload_mcp`。 | `/reload-mcp now` |
| `/browser status` | 查看浏览器 CDP 连接。 | `/browser status` |
| `/browser connect [url]` | 连接 Chromium-family 浏览器 CDP。默认 `http://127.0.0.1:9222`。 | `/browser connect` |
| `/browser disconnect` | 断开 CDP 浏览器连接。 | `/browser disconnect` |
| `/plugins` | 查看插件状态。 | `/plugins` |
| `/bundles` | 列出技能 bundle。 | `/bundles` |

## 22. TUI 子代理、回放和回滚命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/agents` | 打开 spawn-tree/subagent 面板。别名：`/tasks`。 | `/agents` |
| `/agents pause` | 暂停 delegation。 | `/agents pause` |
| `/agents resume` | 恢复 delegation。 | `/agents resume` |
| `/agents status` | 查看 delegation 状态。 | `/agents status` |
| `/replay` | 回放本会话最近完成的 spawn tree。 | `/replay last` |
| `/replay list` | 列出磁盘归档的 spawn tree。 | `/replay list` |
| `/replay load <path>` | 从磁盘加载 spawn tree 快照。 | `/replay load /path/to/tree.json` |
| `/replay-diff <a> <b>` | 对比两个完成的 spawn tree。 | `/replay-diff 1 2` |
| `/rollback` | 列出 checkpoint。 | `/rollback` |
| `/rollback diff <checkpoint>` | 查看 checkpoint diff。 | `/rollback diff abc123` |
| `/rollback <checkpoint> [file]` | 恢复整个 workspace 或单个文件。 | `/rollback abc123 src/app.py` |
| `/snapshot create` | 创建 Hermes 配置/状态快照。 | `/snapshot create` |
| `/snapshot restore <id>` | 恢复状态快照。 | `/snapshot restore 20260527` |

## 23. TUI 计划任务、Kanban、长期目标命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/cron <subcommand>` | 管理定时任务。常见子命令：`list`、`add`、`edit`、`pause`、`resume`、`run`、`remove`。 | `/cron list` |
| `/kanban <subcommand>` | 多 profile 协作看板。支持任务、指派、评论、完成、阻塞、调度、统计等。 | `/kanban list` |
| `/curator <subcommand>` | 后台技能维护。支持 `status`、`run`、`pause`、`resume`、`pin`、`restore` 等。 | `/curator status` |
| `/goal [text/status/pause/resume/clear]` | 设置长期目标，Hermes 跨 turn 持续推进。 | `/goal 完成 dashboard 文档` |
| `/subgoal [text/remove N/clear]` | 给当前 goal 添加或管理额外验收标准。 | `/subgoal 必须包含 TUI 命令表` |

## 24. TUI 配置、平台与诊断命令

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `/config` | 查看当前配置。 | `/config` |
| `/profile` | 查看当前 profile 名和 home 目录。 | `/profile` |
| `/whoami` | 查看 slash 命令权限。 | `/whoami` |
| `/platforms` | 查看 gateway/消息平台状态。别名：`/gateway`。 | `/platforms` |
| `/footer [on/off/status]` | 控制 gateway 回复末尾运行元数据 footer。 | `/footer status` |
| `/codex-runtime [auto/codex_app_server]` | 切换 OpenAI/Codex 模型 runtime。 | `/codex-runtime auto` |
| `/voice [on/off/tts/status]` | 控制语音模式和 TTS。 | `/voice status` |
| `/busy [queue/steer/interrupt/status]` | 控制 Hermes 工作时按 Enter 的行为。 | `/busy queue` |
| `/setup` | 暂停 TUI 并运行 `hermes setup`。 | `/setup` |
| `/debug` | 生成并上传 debug report。 | `/debug` |
| `/mem` | 查看 TUI Node 进程 V8 heap/RSS。 | `/mem` |
| `/heapdump` | 写 V8 heap snapshot 和诊断文件。 | `/heapdump` |
| `/update` | 退出 TUI 并运行更新流程。 | `/update` |

## 25. 消息平台专用命令

这些命令主要在 Telegram、Discord、Slack 等 gateway 中使用，不是普通 TUI 的主路径：

| 命令 | 用途 |
| --- | --- |
| `/approve [session|always]` | 批准待处理危险命令。 |
| `/deny` | 拒绝待处理危险命令。 |
| `/restart` | 平滑重启 gateway。 |
| `/sethome` | 设置当前聊天为 home channel。 |
| `/topic [off/help/session-id]` | Telegram DM topic sessions 管理。 |
| `/commands [page]` | 分页浏览所有 gateway 命令和技能。 |
| `/platform <pause/resume/list> [name]` | 暂停、恢复或列出失败平台。 |

## 26. 快速掌握路线

第一次熟悉项目建议按这个顺序：

1. 启动 `hermes dashboard --tui`。
2. 在 Sessions 看历史会话，理解 Hermes 如何记录消息、工具调用和来源平台。
3. 打开 Chat，输入 `/help`，熟悉 TUI 命令和快捷键。
4. 在 Chat 里试 `/model`、`/status`、`/usage`、`/details expanded`。
5. 到 Keys 配好模型 provider 的 API key。
6. 到 Config 看主模型、agent、terminal、display、memory、security 配置。
7. 到 Skills 看当前启用了哪些技能和工具集。
8. 到 Logs 学会看 `agent`、`gateway`、`errors`。
9. 到 Cron 创建一个简单 local 定时任务，试 Trigger Now。
10. 到 Profiles 创建一个 `coder` profile，编辑 SOUL.md。
11. 到 Plugins 看插件状态，理解哪些能力来自插件。
12. 到 Models 和 Analytics 看成本、Token 和模型使用情况。

## 27. 日常工作流建议

### 写代码或改项目

1. 进入 Chat 或 `hermes --tui`。
2. 用自然语言描述任务。
3. 需要切模型时用 `/model`。
4. 工具输出太少用 `/verbose` 或 `/details expanded`。
5. 当前会话太长用 `/compress <focus>`。
6. 做完后用 `/usage` 看成本，用 Sessions 保存/查找结果。

### 排查 Agent 没反应

1. Chat 里先 `/status`。
2. 看 Dashboard Logs 的 `agent` 和 `errors`。
3. 如果是消息平台，查 `gateway` 日志。
4. 改了密钥后在 TUI 用 `/reload`。
5. 改了 gateway 配置后用 Dashboard 的 Restart Gateway。

### 管理模型成本

1. Models 页面看每个模型的 Token 和成本。
2. Analytics 页面看 7/30/90 天趋势。
3. 用 Models 页面把便宜模型分配给辅助任务。
4. 在 TUI 中用 `/fast normal`、`/reasoning low` 控制高成本模式。

### 管理长期自动化

1. Profiles 为不同任务建立不同 Agent 配置。
2. Cron 绑定 profile 执行周期任务。
3. Logs 检查 cron 失败原因。
4. Sessions 搜索 cron 产生的历史结果。
5. Plugins/Skills 扩展自动化能力。

## 28. 记住这几个高频命令

```text
/help                 查看命令
/model                切模型
/status               看会话状态
/usage                看 Token/成本
/resume               恢复旧会话
/details expanded     展开工具/思考详情
/tools enable web     开工具集
/reload               重读 .env
/reload-skills        重扫技能
/copy                 复制最近助手回复
/clear                新会话
/quit                 退出
```

如果你只记一条：先用 `/help`。它会根据当前运行环境显示真实可用的命令和快捷键。
