param([switch]$DownloadModels)
$ErrorActionPreference = 'Stop'
$ModelProjectDir = $PSScriptRoot
$ModelEnvironmentDir = Join-Path $ModelProjectDir '.model-env'
python -m venv $ModelEnvironmentDir
if ($LASTEXITCODE -ne 0) { throw 'Could not create model environment' }
$ModelPython = Join-Path $ModelEnvironmentDir 'Scripts\python.exe'
& $ModelPython -m pip install 'torch==2.9.0' --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed' }
& $ModelPython -m pip install -r (Join-Path $ModelProjectDir 'requirements-models.txt')
if ($LASTEXITCODE -ne 0) { throw 'Model dependencies installation failed' }
$ModelConfig = @{python=$ModelPython} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $ModelProjectDir 'model_runtime.local.json'),$ModelConfig,[System.Text.UTF8Encoding]::new($false))
if ($DownloadModels) {
    & $ModelPython -X utf8 (Join-Path $ModelProjectDir 'download_comparison_models.py') --root (Join-Path $ModelProjectDir 'models')
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
}
