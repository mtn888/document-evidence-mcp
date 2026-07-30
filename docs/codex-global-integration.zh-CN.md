# Codex 全局 document-evidence 集成记录

## 目标

让 `document_evidence` MCP 不依赖项目级 `.codex/config.toml`，在任意本地
Codex 项目中默认可发现；同时以全局指令、可复用 skill 和生命周期 hook 约束
证据工作流，避免无关批量导入和上下文膨胀。

验证日期：2026-07-30。

## 有效全局位置

`C:\Users\mtn88\.codex` 是指向 `D:\Codexhome` 的目录符号链接。实际维护：

| 层 | 路径 | 作用 |
|---|---|---|
| 用户配置 | `D:\Codexhome\config.toml` | 注册并启用全局 stdio MCP |
| 全局指令 | `D:\Codexhome\AGENTS.md` | 默认使用边界与证据引用约定 |
| skill | `D:\Codexhome\skills\document-evidence` | 可显式或隐式触发的取证工作流 |
| hook 脚本 | `D:\Codexhome\hooks\document-evidence-context.py` | 注入简短的可用性与边界提示 |
| hook 配置 | `D:\Codexhome\hooks.json` | `SessionStart` 与 `SubagentStart` |
| 独立运行时 | `D:\Codexhome\document-evidence-mcp-runtime` | Python、Paddle GPU 与 MCP 命令 |
| 模型缓存 | `D:\Codexhome\models\paddlex` | 已下载的真实 PaddleX/PaddleOCR 模型 |
| 共享索引 | `D:\Codexhome\document-evidence-store` | 跨项目复用的内容对象、版本与 FTS |

运行时已从通过验收的 wheel 非 editable 安装，导入源码不依赖当前工作目录或
`X:` 仓库的 `src/`。MCP 进程的 `cwd` 固定为 `D:\Codexhome`。

## 用户级 MCP

有效配置的核心部分如下：

```toml
[mcp_servers.document_evidence]
command = 'D:\Codexhome\document-evidence-mcp-runtime\Scripts\document-evidence-mcp.exe'
cwd = 'D:\Codexhome'
enabled = true
required = false
startup_timeout_sec = 60
tool_timeout_sec = 1800

[mcp_servers.document_evidence.env]
DOCUMENT_EVIDENCE_STORE = 'D:\Codexhome\document-evidence-store'
DOCUMENT_EVIDENCE_OCR_PROVIDER = 'paddleocr'
DOCUMENT_EVIDENCE_OCR_DEVICE = 'gpu:0'
PADDLE_PDX_CACHE_HOME = 'D:\Codexhome\models\paddlex'
PADDLE_OCR_BASE_DIR = 'D:\Codexhome\models\paddleocr'
PADDLE_PDX_MODEL_SOURCE = 'bos'
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
```

全局配置故意省略 `DOCUMENT_EVIDENCE_ALLOWED_ROOTS`，因此任意项目可显式导入
其任务所需的本地文件。服务不会自动扫描或自动导入；读取仍从 MCP
`ingest_document` 调用开始。若以后需要收紧范围，可用 Windows 分号分隔多个
允许根目录。

`required=false` 保证 OCR 运行时临时故障不会阻断所有 Codex 任务启动；
`enabled=true` 保证正常情况下始终注册工具。

## 指令、skill 与 hook

全局 `AGENTS.md` 规定：

1. 本地 PDF、Office、文本、图片、扫描件和可追溯引用任务默认使用
   `document_evidence`；
2. 只导入当前任务相关文档，复用内容哈希缓存；
3. 先小范围检索，再精取证据；数字、条款、表格、低置信度 OCR 才裁剪复核；
4. 代码定义和调用关系仍使用代码库发现工具。

`$document-evidence` skill 已通过 `quick_validate.py`，允许隐式触发，并声明对
`document_evidence` MCP 的依赖。

hook 在 `startup`、`resume`、`clear`、`compact` 以及子代理启动时注入不超过
一小段的开发上下文。它只检查运行时文件是否存在并输出边界提示，不扫描项目、
不启动 OCR、不导入文档。两个新增命令 hook 的当前定义哈希已写入用户级
`hooks.state`，避免新会话因未信任而跳过。

## 实际验证

1. 当前 Codex CLI 可完整解析用户配置；`codex mcp list` 与
   `codex mcp get document_evidence` 均显示服务器为 `enabled`。
2. hook 脚本用 `SessionStart` 和 `SubagentStart` 两种真实 JSON 输入单独执行，
   均正常输出简短上下文。
3. skill 目录通过官方 `quick_validate.py`。
4. 从与仓库无关的项目目录
   `C:\Users\mtn88\Documents\Codex\2026-07-30\wo` 启动全新、ephemeral Codex
   进程，实际调用全局 MCP：
   - `doctor.ocr_available=true`；
   - `search_evidence("催化转化器", limit=1)` 命中
     `doc_7e18839e0c1e01f1_b19168a1f5_r1:e000011`；
   - 命中文本为“第1部分：三元催化转化器”，页码 1；
   - 进程退出码为 0。

现有已打开任务的工具清单可能是启动时快照；新建任务会读取全局配置。若桌面端
没有立即刷新 skill 或 MCP，关闭并重新打开 Codex 后生效。

## 回滚

本次全局状态快照位于：

```text
D:\Codexhome\backups\document-evidence-global-20260730-174834
```

回滚前应先退出 Codex，再恢复其中的 `config.toml`、`AGENTS.md` 与
`hooks.json`。三个核心文件均保留本次全局集成前的状态；仓库代码和 D 盘模型、
store 不受配置回滚影响。
