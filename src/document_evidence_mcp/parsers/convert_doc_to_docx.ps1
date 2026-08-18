#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,

    [Parameter(Mandatory = $true)]
    [string]$DestinationPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ($env:OS -ne "Windows_NT") {
    throw "Legacy .doc conversion requires Windows and Microsoft Word."
}

$source = (Resolve-Path -LiteralPath $SourcePath).Path
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Source file does not exist: $source"
}
if ([System.IO.Path]::GetExtension($source) -ine ".doc") {
    throw "Source must use the .doc extension: $source"
}

$destination = [System.IO.Path]::GetFullPath($DestinationPath)
if ([System.IO.Path]::GetExtension($destination) -ine ".docx") {
    throw "Destination must use the .docx extension: $destination"
}
if ($source -eq $destination) {
    throw "Source and destination must be different files."
}
if (Test-Path -LiteralPath $destination) {
    throw "Destination already exists: $destination"
}

$destinationDirectory = Split-Path -Parent $destination
[void][System.IO.Directory]::CreateDirectory($destinationDirectory)

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    # 3 = msoAutomationSecurityForceDisable. Never execute macros from an ingested file.
    $word.AutomationSecurity = 3
    $word.Options.SaveNormalPrompt = $false
    $document = $word.Documents.Open($source, $false, $true, $false)
    # 16 = wdFormatDocumentDefault (DOCX for current Microsoft Word).
    $document.SaveAs2($destination, 16)
} finally {
    if ($null -ne $document) {
        $document.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
    }
    if ($null -ne $word) {
        $word.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$result = Get-Item -LiteralPath $destination
if ($result.Length -lt 4) {
    throw "Microsoft Word created an empty or truncated DOCX: $destination"
}
$stream = [System.IO.File]::OpenRead($destination)
try {
    if ($stream.ReadByte() -ne 0x50 -or $stream.ReadByte() -ne 0x4B) {
        throw "Microsoft Word output is not an OOXML ZIP container: $destination"
    }
} finally {
    $stream.Dispose()
}

[PSCustomObject]@{
    DestinationPath = $destination
    Length = $result.Length
} | ConvertTo-Json -Compress
