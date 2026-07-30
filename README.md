# document-evidence-mcp

一个面向 Codex/其他 MCP 客户端的本地文档证据层：文档首次导入时完整解析并持久化，后续问答只检索 SQLite 索引，返回少量带来源坐标的证据。

它刻意保持“薄”：

- 不重写 PDF、OOXML、OCR 或表格识别引擎；
- 原生 PDF、DOCX、XLSX、PPTX 优先读取结构，不做无意义 OCR；
- 扫描 PDF 与图片可选接入 PaddleOCR PP-StructureV3；
- 源文件按 SHA-256 内容寻址，换路径不重复解析；
- SQLite FTS 默认使用 trigram tokenizer，兼顾中文、英文和德文检索；
- MCP 响应有总字符预算，不回传整份 OCR、整页图片或二进制；
- 需要复核时只渲染 PDF 的一个 bbox，返回本地 artifact 路径。

当前状态：`0.1.0` Alpha。首版已覆盖本地持久化、文本/Office/PDF 原生解析、可选 OCR 路由和 PDF 局部裁剪；语义向量检索、OCRmyPDF 归档与逐单元格表格 API 属于后续能力。

## 工具

| MCP 工具 | 用途 |
|---|---|
| `ingest_document` | 首次全量导入；相同内容与配置直接命中缓存 |
| `search_evidence` | FTS 检索，返回少量证据 ID、页码、bbox、置信度 |
| `get_evidence` | 按稳定 ID 精确读取证据块 |
| `list_documents` | 列出文档版本，不返回正文 |
| `get_document` | 查看文档清单与曾见过的源路径 |
| `render_crop` | 仅将指定 PDF 区域渲染为本地 PNG |
| `doctor` | 检查 SQLite/FTS、解析器与 OCR 可用性 |

支持格式：

- PDF：PyMuPDF 原生文本、表格、页码与 PDF point bbox；
- DOCX：段落、标题样式、表格；
- XLSX/XLSM：工作表、行、单元格地址与公式文本；
- PPTX：幻灯片文本、表格与 shape bbox；
- TXT/Markdown/CSV/TSV/JSON/XML/HTML；
- PNG/JPEG/TIFF/BMP/WebP：需要启用 OCR。

## 安装

需要 Python 3.11 或更新版本。推荐使用 `uv`：

```powershell
git clone https://github.com/mtn888/document-evidence-mcp.git
Set-Location document-evidence-mcp
uv sync --extra dev
uv run document-evidence doctor
```

如果仓库位于 Windows UNC/网络映射盘，而 `doctor` 报告 PyMuPDF 原生扩展无法加载，请把虚拟环境放到本机磁盘（项目代码仍可留在网络盘）：

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\document-evidence-mcp-venv"
uv sync --extra dev
uv run document-evidence doctor
```

PyMuPDF 官方安装说明也将 Windows `_extra` DLL load failure 与 Visual C++ Redistributable/原生加载环境列为首要排查项，并推荐新代码使用 `import pymupdf` 而非旧 `fitz` 别名：[PyMuPDF installation](https://pymupdf.readthedocs.io/en/latest/installation.html)。

### Windows GPU + PaddleOCR 完整配置

PP-StructureV3 除 `paddleocr` 外还需要 `paddlex[ocr]`；本项目的 `ocr` extra
已经同时声明二者。PaddlePaddle 推理运行时仍需按硬件单独安装。

当前已验证的 Windows 配置使用独立 D 盘环境，避免映射盘上的原生 DLL
加载问题，也不覆盖系统已有 CUDA：

```powershell
.\scripts\setup_paddleocr.ps1 -ValidateSamples
```

脚本固定使用：

- Python 3.12.11：`D:\Codexhome\document-evidence-mcp-runtime`；
- PaddlePaddle GPU 3.3.0 官方 CUDA 12.9 wheel；
- PaddleOCR 3.x + `paddlex[ocr]`；
- 模型：`D:\Codexhome\models\paddlex`；
- 文档库：`D:\Codexhome\document-evidence-store`。

模型在第一次真实 OCR 时从 Paddle 官方 BOS 下载。PP-StructureV3 使用
`PADDLE_PDX_CACHE_HOME`，旧 PaddleOCR 下载器使用 `PADDLE_OCR_BASE_DIR`；
两者都必须配置，不能只设置旧变量。当前适配器关闭公式、印章、图表和区域识别，
保留布局、OCR 和表格识别，减少无关模型。只导入带可靠文本层的 PDF 或 Office
文件不会触发 OCR。

如果不运行脚本，可手动安装当前已验证的 GPU wheel：

```powershell
uv venv --python 3.12.11 D:\Codexhome\document-evidence-mcp-runtime
$python = 'D:\Codexhome\document-evidence-mcp-runtime\Scripts\python.exe'
uv pip install --python $python --link-mode copy `
  'https://paddle-whl.bj.bcebos.com/stable/cu129/paddlepaddle-gpu/paddlepaddle_gpu-3.3.0-cp312-cp312-win_amd64.whl'
uv pip install --python $python --link-mode copy --editable '.[ocr,dev]'
```

本机验证环境、9 份 PDF 的结果和已知空白页边界见
[真实 PaddleOCR 验证记录](docs/paddleocr-validation.zh-CN.md)。

## 命令行试用

```powershell
uv run document-evidence ingest 'D:\docs\standard.pdf'
uv run document-evidence search '安全阀' --limit 4 --max-chars 5000
uv run document-evidence list
```

首次导入后的典型返回：

```json
{
  "document_id": "doc_..._r1",
  "cached": false,
  "status": "completed",
  "source_sha256": "...",
  "profile_hash": "...",
  "evidence_count": 143
}
```

再次导入同一内容（即使文件换了路径）会返回相同 `document_id` 且 `cached: true`。只有源内容、解析配置、语言/OCR 引擎版本发生变化，或显式使用 `--force` 时才生成新版本。

## 配置 Codex

先完成安装。以下示例将读取范围限制为本仓库的 `pdf/`，适合写入可信项目的
`.codex/config.toml`：

```toml
[mcp_servers.document_evidence]
command = 'D:\Codexhome\document-evidence-mcp-runtime\Scripts\document-evidence-mcp.exe'
cwd = 'D:\Codexhome\document-evidence-mcp'
startup_timeout_sec = 60
tool_timeout_sec = 1800
required = false

[mcp_servers.document_evidence.env]
DOCUMENT_EVIDENCE_STORE = 'D:\Codexhome\document-evidence-store'
DOCUMENT_EVIDENCE_OCR_PROVIDER = 'paddleocr'
DOCUMENT_EVIDENCE_OCR_DEVICE = 'gpu:0'
DOCUMENT_EVIDENCE_ALLOWED_ROOTS = 'D:\Codexhome\document-evidence-mcp\pdf'
PADDLE_PDX_CACHE_HOME = 'D:\Codexhome\models\paddlex'
PADDLE_OCR_BASE_DIR = 'D:\Codexhome\models\paddleocr'
PADDLE_PDX_MODEL_SOURCE = 'bos'
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
```

`DOCUMENT_EVIDENCE_ALLOWED_ROOTS` 使用当前操作系统的路径分隔符；Windows 为分号。项目级配置只会在 Codex 信任该项目后加载。字段依据当前 Codex 配置参考中的 `mcp_servers.<id>.command`、`args`、`cwd`、`env`、启动/工具超时定义：[Codex config.toml reference](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)。

如需让任意项目默认可用，应把 MCP 写入用户级 `~/.codex/config.toml`，把
`cwd` 设为稳定的本机目录，并省略 `DOCUMENT_EVIDENCE_ALLOWED_ROOTS`；这表示
服务端不预先限制可导入根目录，但仍只有显式调用 `ingest_document` 才会读取
文件。建议同时用用户级 `AGENTS.md`、skill 和轻量 `SessionStart` hook 约束为
“只导入当前任务相关文档”。本机已验证的完整配置、文件位置、hook 信任与跨项目
实测见[全局 Codex 集成记录](docs/codex-global-integration.zh-CN.md)。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `DOCUMENT_EVIDENCE_STORE` | Windows `%LOCALAPPDATA%\document-evidence-mcp` | 对象、版本 artifact 与 SQLite |
| `DOCUMENT_EVIDENCE_ALLOWED_ROOTS` | 空（不限制） | 允许导入的根目录列表 |
| `DOCUMENT_EVIDENCE_OCR_PROVIDER` | `none` | `none` 或 `paddleocr` |
| `DOCUMENT_EVIDENCE_OCR_DEVICE` | 空（Paddle 自动选择） | 如 `gpu:0` 或 `cpu` |
| `DOCUMENT_EVIDENCE_MAX_FILE_BYTES` | `1073741824` | 单文件上限 |
| `DOCUMENT_EVIDENCE_CHUNK_CHARS` | `1600` | 单证据块目标上限 |
| `DOCUMENT_EVIDENCE_CHUNK_OVERLAP` | `160` | 文本块重叠 |
| `DOCUMENT_EVIDENCE_MAX_SEARCH_CHARS` | `12000` | 单次 MCP 响应正文硬上限 |
| `DOCUMENT_EVIDENCE_MAX_SEARCH_HITS` | `20` | 单次证据条数硬上限 |
| `PADDLE_PDX_CACHE_HOME` | `%USERPROFILE%\.paddlex` | PP-StructureV3/PaddleX 模型缓存根目录 |
| `PADDLE_OCR_BASE_DIR` | `%USERPROFILE%\.paddleocr` | 旧 PaddleOCR 模型缓存根目录 |
| `PADDLE_PDX_MODEL_SOURCE` | `huggingface` | 本配置用 `bos` 直连 Paddle 官方模型源 |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | `False` | `True` 时跳过源连通性探测，仍按所选源下载缺失模型 |

## 推荐工作流

1. 用 `ingest_document` 导入一次；扫描件在首次导入时 OCR。
2. 用短关键词调用 `search_evidence`，通常取 3–6 条。
3. 用 `get_evidence` 精取必须引用的证据。
4. 数字、条款号、表格列对齐或低置信度内容才调用 `render_crop`。
5. 不把 `blocks.jsonl`、整份 OCR 文本或所有页面 PNG 直接放进对话。

架构、身份规则和已知边界见 [中文架构说明](docs/architecture.zh-CN.md)。

## 开发验证

```powershell
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build
```

真实 PDF 回归（需要已安装的 OCR/GPU 环境）：

```powershell
$env:DOCUMENT_EVIDENCE_STORE = 'D:\Codexhome\document-evidence-store'
$env:DOCUMENT_EVIDENCE_OCR_PROVIDER = 'paddleocr'
$env:DOCUMENT_EVIDENCE_OCR_DEVICE = 'gpu:0'
$env:PADDLE_PDX_CACHE_HOME = 'D:\Codexhome\models\paddlex'
$env:PADDLE_PDX_MODEL_SOURCE = 'bos'
D:\Codexhome\document-evidence-mcp-runtime\Scripts\python.exe `
  .\scripts\validate_real_pdfs.py .\pdf `
  --report .\artifacts\reports\real-pdf-validation.json
```

GitHub Actions 会在 Windows/Linux 与 Python 3.11/3.13 上执行同一组 lint、测试和构建检查。

本项目采用 MIT 许可证。
