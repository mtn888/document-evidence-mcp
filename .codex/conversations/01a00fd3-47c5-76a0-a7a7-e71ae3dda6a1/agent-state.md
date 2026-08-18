---
schema: 2
conversation_id: 01a00fd3-47c5-76a0-a7a7-e71ae3dda6a1
status: completed
updated_at: 2026-08-18T00:45:00+08:00
base_revision: 3d2264d3bc8d0dd535d5dea7fdfb4b52d09321ac
scope: src/document_evidence_mcp; tests; README.md; docs/architecture.zh-CN.md; .env.example; .codex; D:/Codexhome/document-evidence-mcp; D:/Codexhome/document-evidence-mcp-runtime
last_verified_commit: 9199ee93e22f50702013660ace728c6dec9ee7c4
goal_id: null
plan_version: 3
---

# 对话任务状态

## 固定目标与完成门槛

- 目标（不等同于 goal 模式）：为 `document-evidence-mcp` 增加旧版 Word `.doc` 文件处理，复用 `E:\python\COC\scripts\tools` 中的适用工具。
- 完成条件：`.doc` 可经公共导入/解析接口进入现有证据管线；覆盖成功及失败路径测试；相关中文文档同步；现有质量检查无回归，并完成至少一次真实 `.doc` 端到端验证；变更已提交，D 盘生产 clone 与运行时加载该提交，并通过部署后真实 `.doc` 验收。
- 持久 goal：无；只有用户明确要求时才创建。
- 允许修改计划的条件：用户改变需求、原步骤被证据证明不可行，或记录了明确阻塞。

## 执行计划（步骤 ID 和顺序固定）

1. [x] P1：确认现有文档处理架构、`.doc` 缺口及 COC 工具的接口与运行依赖。
2. [x] P2：实现 `.doc` 处理，并补齐单元/集成测试及受影响的中文文档。
3. [x] P3：运行静态检查、完整测试与真实 `.doc` 端到端验收，复核 diff 和范围冲突。
4. [x] P4：提交已验证变更，并将 D 盘生产 clone 快进到该提交且保留既有本地修改。
5. [x] P5：重装 D 盘生产运行时、重启旧 MCP 服务进程并完成部署后真实 `.doc` 验收。
6. [x] P6：推送本地 main 到 origin/main 并核对远端提交。

## 已确认事实与约束

- Windows 工作区使用 PowerShell；不得使用 `rg`；临时生成物放在 `D:\Codexhome`。
- Git 工作区起点干净，HEAD 为 `3d2264d`。
- `document-evidence-mcp` 与 `E:\python\COC` 均已被 codebase-memory 索引。
- COC 参考工具依赖 Windows PowerShell 5.1 与 Microsoft Word COM；没有 LibreOffice 后端、调用方或自动测试。

## 已完成

- 增加 `.doc` 路由、禁用宏的 Word COM 转换、可操作诊断与 300 秒可配置超时。
- 成功转换的 DOCX 按源 SHA-256 和转换器版本持久缓存；强制重建复用，损坏时自动再生成。
- `.doc` 不同解析 profile 共享源/转换器锁，避免并发重复启动 Word。
- 中文 README、架构文档和环境变量示例已同步。
- 真实 COC DOC 完成转换、索引、缓存复用和检索验收。
- 功能提交 `595077e` 已同步到 D 盘生产 clone；原有两处未提交修改按哈希确认未变。
- D 盘生产运行时已非 editable 重装，源码与已安装 DOC 解析器/PowerShell 脚本哈希一致。
- 部署后真实 DOC：147 个证据块、2 个检索命中、revision 2 复用衍生缓存，未遗留新 Word 进程；生产 stdio MCP 握手与 `doctor` 调用通过。
- GitHub `origin/main` 已从 `3d2264d` 快进到 `9199ee9`，推送后本地与远端 ahead/behind 均为 0。

## 进行中

- 无。

## 关键决策与提案

- 优先复用 COC 已有转换工具，但最终集成必须符合 MCP 现有安全边界与错误模型。

## 计划变更记录

- 用户要求不要在每次重解析后删除转换结果；P2 的范围不变，实现决策调整为把成功转换的 DOCX 按源 SHA-256 与转换器版本持久缓存并复用。
- 2026-08-18 用户明确要求提交并部署到本机；计划版本升至 2，在既有 P1–P3 后追加 P4–P5，不改变原步骤。
- 2026-08-18 用户明确授权推送远端；计划版本升至 3，追加 P6，仅推送 `main`，不创建 PR。

## 修改与验证证据

- 修改文件：`parsers/doc.py`、随包 PowerShell 脚本、router、config、service、测试、README、中文架构与环境示例。
- Git/commit：`595077e`（功能提交）、`9199ee9`（部署记录）；D 盘生产 clone 与 `origin/main` 均已同步。
- 测试：D 盘 Python 3.13 隔离环境执行 18 tests 全通过，覆盖率 80.91%；ruff format/check、`uv lock --check`、`uv build` 全通过。
- 真实验收：`D:\Codexhome\temp\document-evidence-mcp-doc\final-real-20260817-135323`；147 个证据块、2 个检索命中，强制重建保持 DOCX 缓存修改时间不变。
- wheel：`dist\document_evidence_mcp-0.1.0-py3-none-any.whl` 已包含 `doc.py` 与 `convert_doc_to_docx.ps1`。
- 部署验收：`D:\Codexhome\temp\document-evidence-deploy-20260818-002500`；运行时安装源为 `file:///D:/Codexhome/document-evidence-mcp`，`dir_info` 不含 editable。

## 未决问题与风险

- 超时会终止 PowerShell 子进程，但极端 Word COM 卡死时仍可能由 Windows 留下孤立 Word 进程；不能为清理而误杀用户已有 Word 会话。
- D 盘生产 clone 现有 `.gitignore`、`docs/codex-global-integration.zh-CN.md` 未提交修改必须保留，且未包含在远端推送中。
- 当前桌面任务的旧 MCP transport 在进程重启后关闭；全新生产 stdio 连接已验证通过，后续新连接会加载部署版本。

## 下一步

1. 无。
