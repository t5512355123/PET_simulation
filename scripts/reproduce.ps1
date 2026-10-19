# 在已啟用的 pet-simulation 環境中，重現全部簡化模擬驗證。
$ErrorActionPreference = 'Stop'
function Invoke-PetStep {
    param([string[]]$Arguments)
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "步驟失敗：python $Arguments" }
}
New-Item -ItemType Directory -Force -Path outputs | Out-Null
& python -m pytest -q | Tee-Object -FilePath outputs/pytest.txt
if ($LASTEXITCODE -ne 0) { throw 'pytest 驗證失敗。' }
Invoke-PetStep -Arguments @('-m', 'pet_sim.cli', 'validate')
Invoke-PetStep -Arguments @('-m', 'pet_sim.cli', 'demo')
Invoke-PetStep -Arguments @('-m', 'pet_sim.cli', 'sweep')
Invoke-PetStep -Arguments @('scripts/build_report.py')
