# PythonPath can be Comfy Desktop's standalone-env\python.exe.
param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
if ($PythonPath) {
    & $PythonPath (Join-Path $PSScriptRoot 'setup.py') @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $PSScriptRoot 'setup.py') @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python (Join-Path $PSScriptRoot 'setup.py') @args
} else {
    throw 'Python 3.10-3.14 is required. Install Python or pass -PythonPath to Comfy Desktop Python.'
}
exit $LASTEXITCODE
