# 在目前的 PowerShell 載入 Conda，並啟用本研究的獨立環境。
# 使用方式：. .\scripts\activate.ps1 （開頭的點表示載入到目前工作階段）
$petConda = Join-Path $env:USERPROFILE 'anaconda3\Scripts\conda.exe'
if (-not (Test-Path -LiteralPath $petConda)) {
    throw '找不到使用者目錄中的 Anaconda，請修改 scripts/activate.ps1 的 petConda 路徑。'
}
(& $petConda 'shell.powershell' 'hook') | Out-String | Invoke-Expression
conda activate pet-simulation
if ($LASTEXITCODE -ne 0) { throw '無法啟用 pet-simulation 環境。' }
Write-Host "已啟用環境：$env:CONDA_PREFIX"
