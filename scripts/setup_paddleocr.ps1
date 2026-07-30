[CmdletBinding()]
param(
    [string]$RuntimeRoot = 'D:\Codexhome\document-evidence-mcp-runtime',
    [string]$ModelRoot = 'D:\Codexhome\models',
    [string]$StoreRoot = 'D:\Codexhome\document-evidence-store',
    [string]$PythonVersion = '3.12.11',
    [switch]$ValidateSamples
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$gpuWheel = 'https://paddle-whl.bj.bcebos.com/stable/cu129/paddlepaddle-gpu/' +
    'paddlepaddle_gpu-3.3.0-cp312-cp312-win_amd64.whl'
$python = Join-Path $RuntimeRoot 'Scripts\python.exe'

New-Item -ItemType Directory -Force -Path $ModelRoot, $StoreRoot | Out-Null
if (-not (Test-Path -LiteralPath $python)) {
    uv venv --python $PythonVersion $RuntimeRoot
}

uv pip install --python $python --link-mode copy $gpuWheel
uv pip install --python $python --link-mode copy "${projectRoot}[ocr,dev]"

$env:DOCUMENT_EVIDENCE_STORE = $StoreRoot
$env:DOCUMENT_EVIDENCE_ALLOWED_ROOTS = Join-Path $projectRoot 'pdf'
$env:DOCUMENT_EVIDENCE_OCR_PROVIDER = 'paddleocr'
$env:DOCUMENT_EVIDENCE_OCR_DEVICE = 'gpu:0'
$env:PADDLE_PDX_CACHE_HOME = Join-Path $ModelRoot 'paddlex'
$env:PADDLE_OCR_BASE_DIR = Join-Path $ModelRoot 'paddleocr'
$env:PADDLE_PDX_MODEL_SOURCE = 'bos'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'

& $python -c @'
import json
import paddle

paddle.utils.run_check()
paddle.set_device("gpu:0")
value = float((paddle.arange(1, 6, dtype="float32") ** 2).sum().numpy())
print(json.dumps({
    "paddle": paddle.__version__,
    "cuda": paddle.version.cuda(),
    "cudnn": paddle.version.cudnn(),
    "device": paddle.device.get_device(),
    "gpu": paddle.device.cuda.get_device_name(0),
    "tensor_result": value,
}))
'@

& (Join-Path $RuntimeRoot 'Scripts\document-evidence.exe') doctor
if ($ValidateSamples) {
    & $python (Join-Path $projectRoot 'scripts\validate_real_pdfs.py') `
        (Join-Path $projectRoot 'pdf') `
        --report (Join-Path $projectRoot 'artifacts\reports\real-pdf-validation.json')
}
