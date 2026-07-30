# 真实 PaddleOCR 安装与 PDF 验证记录

## 验证环境

验证日期：2026-07-30。

| 项目 | 实际值 |
|---|---|
| 操作系统 | Windows x64 |
| GPU | NVIDIA GeForce RTX 3060 12 GiB，Compute Capability 8.6 |
| 驱动 | 595.79，Driver API 13.2 |
| 系统原有 CUDA | 12.2 / cuDNN 8.6，位于 `E:\ProgramData\cuda` |
| 隔离运行时 | `D:\Codexhome\document-evidence-mcp-runtime` |
| Python | 3.12.11 |
| PaddlePaddle | GPU 3.3.0，Runtime API CUDA 12.9 / cuDNN 9.9 |
| PaddleOCR / PaddleX | 3.7.0 / 3.7.2 |
| 模型缓存 | `D:\Codexhome\models\paddlex` |
| 文档库 | `D:\Codexhome\document-evidence-store` |

Paddle 的 `run_check()` 与实际 GPU 张量运算均通过：

```text
compiled_with_cuda=true
device=gpu:0
gpu=NVIDIA GeForce RTX 3060
cuda=12.9
cudnn=9.9.0
sum([1,2,3,4,5]^2)=55.0
```

CUDA 12.9/cuDNN 9.9 以 Python wheel 形式隔离在 D 盘 venv 中，没有覆盖系统
`CUDA_PATH=E:\ProgramData\cuda` 的 CUDA 12.2。

## 已下载模型

`D:\Codexhome\models\paddlex` 共 965,921,547 bytes，包含：

- `PP-DocLayout_plus-L`；
- `PP-OCRv5_server_det`；
- `PP-OCRv5_server_rec`；
- `latin_PP-OCRv5_mobile_rec`；
- `PP-LCNet_x1_0_table_cls`；
- `SLANeXt_wired`、`SLANet_plus`；
- `RT-DETR-L_wired_table_cell_det`；
- `RT-DETR-L_wireless_table_cell_det`；
- PaddleX 表格子流水线实例化的文档与文本行方向分类模型。

适配器显式关闭公式、印章、图表和区域识别；未下载这些模型。PaddleX 3.7.2
的表格子流水线仍会实例化方向分类模型，即使主流程的方向分类开关关闭。

## 真实样例结果

`pdf/` 共 9 份、172 页、20,092,126 bytes。最终 9 份全部为
`completed`，共 10,772 条证据，其中 OCR 行文本 8,914 条、表格 104 条。

| 样例 | 页数 | 最终证据 | 路由 | 实测首次耗时 | 检索词 |
|---|---:|---:|---|---:|---|
| Accuracy and precision... | 8 | 143 | 英文原生 | 2.635 s | `rolling resistance` |
| CAEPI 36.1-2021... | 8 | 578 | 中文 OCR | 62.590 s | `催化转化器` |
| CONTRIBUTION TO ACCURATE... | 16 | 230 | 英文原生 | 0.612 s | `aerodynamic` |
| DIN17440 | 24 | 3,026 | 德文 OCR | 130.598 s | `Werkstoff` |
| GB/T 17692-2024 | 35 | 1,127 | 原生 + 空白页跳过 | 5.483 s | `净功率` |
| GB/T 6379.5-2006 | 50 | 4,783 | 中文 OCR + 表格 | 281.925 s | `精密度` |
| TL 4800 | 3 | 90 | 德文原生 | 0.559 s | `Sinterstahl` |
| 排气污染物试验流程 | 18 | 595 | 中文 OCR | 33.563 s | `排气污染物` |
| 联电 OSC Measurement Procedure | 10 | 200 | 中英原生 | 1.573 s | `Oxygen Storage` |

最终缓存复测对 9 份文档总耗时 0.541 s，全部返回 `cached=true`，9 个
检索词均返回 3 条命中。详细逐文档 SHA-256、document ID、bbox、置信度和
命中内容见 `artifacts/reports/20260730-real-pdf-validation.json`。

首次单页 PP-StructureV3 调用耗时 150.598 s，其中包含 11 个模型的下载、
解压、GPU 初始化与第一页推理；后续导入复用 D 盘模型。

## 真实测试发现并修复的问题

1. `paddleocr` 基础包可以导入，但 PP-StructureV3 运行时还要求
   `paddlex[ocr]`。项目 `ocr` extra 已补齐。
2. PaddleX 3.7 的 `cell_box_list` 是 NumPy 数组，不能直接做布尔判断。
   适配器已改为显式长度判断并增加回归测试。
3. PaddleOCR 输出 bbox 属于 2×页面图像像素。PDF 解析器现在按实际
   pixmap/page 比例转成 PDF points，并保留原像素尺寸与换算比例。
4. GB/T 17692 的 2、4、6、33、34、35 页经结构和灰度检查确认完全空白：
   无文本、无图像、无绘图、灰度均值 255、非白像素比例 0。解析器现在
   跳过结构性空白页，不再误报 partial。

## bbox 与局部裁剪

对 CAEPI 第 1 页检索 `催化转化器`：

```text
text=第1部分：三元催化转化器
confidence=0.9916295409
bbox=(749.7733, 386.4633, 1063.6784, 415.4605)
coordinate_space=pdf_points
```

以带边距 bbox 实际调用 `render_crop`，生成 672×100 PNG：

```text
D:\Codexhome\document-evidence-store\versions\
doc_7e18839e0c1e01f1_b19168a1f5_r1\crops\
page-00001-fe54ca2a06796862.png
sha256=8327549f18df2c45c526df06faa127d5555b082749c19a0d96c8ba42224f88e1
```

局部图经最小视觉检查，文字与命中内容一致且未裁切。

## 已知质量边界

- DIN17440 是低质量老扫描件，3,009 条 OCR 行中 1,215 条置信度低于 0.5；
  条款引用应优先选高置信度命中，并用 `render_crop` 复核。
- GB/T 6379 的页面尺寸较大，PaddleX 会把约 3250×4660 的输入按最大边
  4000 自动缩放。bbox 仍根据原始 pixmap 尺寸换算回 PDF points。
- 当前语言策略一页只选一个模型族：中文优先、其次德文、否则英文。混合页
  不会同时运行多套 OCR 模型。

## 复测

```powershell
.\scripts\setup_paddleocr.ps1 -ValidateSamples
```

只复测已安装环境：

```powershell
D:\Codexhome\document-evidence-mcp-runtime\Scripts\python.exe `
  .\scripts\validate_real_pdfs.py .\pdf `
  --report .\artifacts\reports\20260730-real-pdf-validation.json
```
