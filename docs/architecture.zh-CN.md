# “薄层” document-evidence-mcp 架构

## 目标

本项目不是新的 OCR 引擎，也不是新的 Office/PDF 渲染器。它只解决四个长期问题：

1. 同一文档只做一次昂贵解析；
2. 不同解析/OCR 引擎输出统一为可追溯证据；
3. Codex 每轮只读取当前问题所需的小片段；
4. 高风险事实可以回到原页局部复核。

## 数据流

```text
本地文件
  → 路径/大小/格式校验
  → SHA-256 内容对象
  → 原生解析器路由
      PDF       → PyMuPDF
      DOC       → Microsoft Word COM → 临时 DOCX → python-docx
      DOCX      → python-docx
      XLSX      → openpyxl
      PPTX      → python-pptx
      扫描页/图像 → 可选 PaddleOCR PP-StructureV3
  → 统一 EvidenceDraft
  → SQLite 元数据 + FTS
  → 有预算的 MCP 检索/取证
  → 必要时 PDF bbox 局部渲染
```

原生结构优先是硬约束。DOCX/XLSX/PPTX 不会先转图片，带可靠文本层的 PDF 也不会默认 OCR。旧版二进制 DOC 在 Windows 上通过本机 Microsoft Word COM 只读转换成工作目录内的临时 DOCX，再复用 DOCX 结构解析器；首次解析成功后，转换结果会原子提升为源内容对象旁的版本化衍生缓存，后续重解析不再启动 Word。源 DOC 不会改写。PDF 单页原生文本少于阈值时，`ocr_mode=auto` 才路由到 OCR。

## 内容与版本身份

缓存身份不是文件名，而是：

```text
source SHA-256
+ parser name/version
+ chunk schema
+ OCR provider/version
+ OCR mode
+ normalized language set
```

上述配置经规范 JSON 计算 `profile_hash`。相同内容换路径后仍复用同一版本，同时把新路径记录到 `document_sources`。`force=true` 生成递增 revision，不覆盖历史版本。

PaddleOCR 从“未安装”变为具体版本时，OCR provider version 会变化，因此不会错误复用之前的 partial 结果。

## 持久化目录

```text
<store>/
  index.sqlite
  objects/
    ab/<full-sha256>/source.<原扩展名>
                     derived-word-com-v1.docx  # 仅旧版 DOC
  versions/
    doc_<sha>_<profile>_r1/
      manifest.json
      blocks.jsonl
      crops/
```

- `objects` 保存不可变源文件副本，使检索和裁剪不依赖原路径继续存在；旧版 DOC 的已验证 DOCX 转换结果按转换器版本作为可再生衍生缓存保存在同一内容目录。
- `versions` 保存可检查、可迁移的文本 artifact。
- `index.sqlite` 是在线查询路径；SQLite WAL 支持多个本地 MCP 进程并行读。
- `ingestion_locks` 防止两个进程同时解析相同 SHA/profile；过期锁可回收。

## 统一证据模型

每个证据块至少包含：

```text
evidence_id, document_id, ordinal, kind, text,
page, bbox, confidence, section, parser, metadata
```

坐标空间由 `metadata.coordinate_space` 明示：

- `pdf_points`：PDF point，72 point/inch；
- `image_pixels`：PaddleOCR 输入图像像素；
- `worksheet_cells`：工作表单元格地址；
- `presentation_emu`：PPTX EMU；
- `none`：DOCX 等无稳定物理坐标的结构证据。

不伪造 DOCX/XLSX 的页码或 bbox。只有解析器能可靠提供时才返回。

## 检索与 token 预算

SQLite 优先创建 FTS5 trigram 索引，便于中英文与德文子串检索；运行环境不支持 trigram 时降级到 `unicode61`，FTS5 不可用时再降级到 `LIKE`。

`search_evidence` 同时限制：

- `limit`：返回块数量；
- `max_chars`：所有证据正文的总字符预算；
- 服务端硬上限：防止客户端把预算参数无限放大。

返回的 `truncated` 明确区分完整证据和预算截断。需要完整块时可用稳定 `evidence_id` 调用 `get_evidence`，仍受总预算约束。

## OCR 边界

核心依赖不包含 PaddleOCR。只有 `DOCUMENT_EVIDENCE_OCR_PROVIDER=paddleocr` 且实际出现扫描页/图片时，才延迟 import 和初始化 PP-StructureV3。

OCR extra 同时安装 `paddleocr` 与 `paddlex[ocr]`；只安装基础
`paddleocr` 虽然能 import，但无法创建 PP-StructureV3。

当前适配器统一提取：

- `overall_ocr_res` 中的行文字、置信度、bbox；
- `table_res_list` 中的表格 HTML，转换为可搜索行/列文本。

PDF 页面以 2× pixmap 送入 OCR。Paddle 返回的图像像素 bbox 在 PDF
解析边界按实际 page/pixmap 比例换算成 `pdf_points`，同时在 metadata 中
保留原图尺寸、原坐标空间和 points-per-pixel。这样 OCR 检索结果可以直接
传给 `render_crop`；直接导入图片时仍保留 `image_pixels`。

完全无文本、图像和绘图对象的结构性空白 PDF 页会在 OCR 前跳过，避免把
“空白页无证据”误报为文档 partial。低文本但含栅格图像或矢量绘图的页面
仍正常进入 OCR。

运行设备可用 `DOCUMENT_EVIDENCE_OCR_DEVICE=gpu:0` 固定。PP-StructureV3
模型缓存使用 `PADDLE_PDX_CACHE_HOME`；`PADDLE_OCR_BASE_DIR` 只覆盖旧
PaddleOCR 下载路径，不能替代前者。当前本机配置选择 Paddle 官方 BOS 模型源。

首版根据语言集合选择一个 Paddle 模型族：含中文优先 `ch`，否则德文优先
`german`，其余 `en`。它不会为每页同时运行多套模型。PP-StructureV3
显式关闭公式、印章、图表和区域识别，保留布局、文字与表格。将来可根据
低置信度或特定区域增加“局部升级”策略，但不应默认全量多引擎齐跑。

OCRmyPDF 的角色是可搜索 PDF 归档，不是索引事实源；因此首版仅保留可选依赖边界，未把它放进导入主路径。

## 安全与故障边界

- 可用 `DOCUMENT_EVIDENCE_ALLOWED_ROOTS` 限制 MCP 能读取的本地根目录。
- 导入前检查真实路径、常规文件和大小上限。
- MCP 不返回文件二进制或 base64；crop 只返回本地路径、尺寸与哈希。
- 原始内容只保存在本地 store；服务器不需要外网。
- OCR 模型下载、许可证和推理数据边界由所选 Paddle 运行环境负责。
- 解析失败不会写入 SQLite 文档记录；内容对象可能已安全去重保存。
- DOC 转换只在实际导入 `.doc` 时启动隐藏的 Word COM 会话；转换前强制禁用宏，且依赖 Windows PowerShell 5.1、Microsoft Word 和有效的 Word COM 注册。非 Windows 或缺少 Word 时，`doctor` 会报告解析器诊断，导入返回可操作错误。
- DOC 首次转换按“源 SHA-256 + 转换器版本”共享导入锁，避免不同解析 profile 并发重复启动 Word；单次转换默认 300 秒超时，可用 `DOCUMENT_EVIDENCE_DOC_CONVERSION_TIMEOUT_SECONDS` 调整。
- PyMuPDF 原生扩展延迟到 PDF 导入/裁剪时加载；单一 PDF 后端故障不会阻止文本或 Office 文档服务启动。Windows 网络盘环境应把虚拟环境放在本机磁盘。

## 首版非目标与后续方向

首版不承诺：

- PDF 之外格式的稳定物理页码；
- 语义向量/embedding 检索；
- 手写、公式和印章的统一高精度识别；
- OCRmyPDF 归档生成；
- Excel 计算引擎或公式重算；
- DOCM/XLS 等其他旧版或含宏 Office 格式解析；
- PDF 证据表格的逐单元格专用 API。

推荐后续顺序：

1. 用 20–30 份中英德标准、法规、论文建立真实评测集；
2. 固定条款定位、表格单元格正确率、阅读顺序与引用复核率阈值；
3. 增加按页/区域缓存的 PaddleOCR-VL 升级路径；
4. 在 FTS 仍不足时再加入可选本地向量索引；
5. 最后增加 OCRmyPDF 可搜索归档，不让归档流程阻塞证据检索。
