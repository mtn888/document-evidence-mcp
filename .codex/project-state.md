# 项目状态

> 项目级人工内容可维护在自动区块之外；自动区块由对话状态汇总生成。

## 项目目标

- 提供可追溯引用的本地文档证据 MCP；开发工作区保留在 X 盘，生产 clone、运行时、模型与数据存储位于 D 盘。

## 已确认决策

- 生产 clone 为 `D:\Codexhome\document-evidence-mcp`，全局 Codex MCP 配置从该目录及其独立运行时启动。
- 生产运行时为 `D:\Codexhome\document-evidence-mcp-runtime`，数据存储为 `D:\Codexhome\document-evidence-store`，PaddleX 模型缓存为 `D:\Codexhome\models\paddlex`。
- 上述路径及生产 clone 的 `3d2264d` 基线已于 2026-08-17 用文件系统、Git 和 `D:\Codexhome\config.toml` 重新核对；历史迁移报告位于 `artifacts/reports/20260730-181623-d-drive-workdir.json`。
- 旧版 Word `.doc` 使用本机 Word COM 转换；转换后的 DOCX 按源 SHA-256 与转换器版本持久缓存，不在每次重解析时重复转换。

## 项目级阻塞

- 无

## 下一步协调事项

- 用户已于 2026-08-18 授权提交并部署旧版 Word `.doc` 支持；当前正在同步 D 盘生产 clone 与运行时，保留生产 clone 的既有未提交修改。

<!-- codex:generated:begin -->

## 对话汇总

> 本区块由 `sync_project_state.py` 根据各对话的 `agent-state.md` 生成。

| 对话 ID | 状态 | 工作范围 | 最近更新 | 已验证版本 | 当前进展 |
|---|---|---|---|---|---|
| 01a00fd3-47c5-76a0-a7a7-e71ae3dda6a1 | 进行中 | src/document_evidence_mcp; tests; README.md; docs/architecture.zh-CN.md; .env.example; .codex; D:/Codexhome/document-evidence-mcp; D:/Codexhome/document-evidence-mcp-runtime | 2026-08-18T00:00:00+08:00 | 3d2264d3bc8d0dd535d5dea7fdfb4b52d09321ac | 增加 `.doc` 路由、禁用宏的 Word COM 转换、可操作诊断与 300 秒可配置超时。 |

## 范围冲突

- 无

<!-- codex:generated:end -->
