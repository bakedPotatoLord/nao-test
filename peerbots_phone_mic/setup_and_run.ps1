$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '=== Peerbots Phone Microphone (Windows) ==='
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3.11 -c 'import sys; assert sys.version_info >= (3,9)' 2>$null
  if ($LASTEXITCODE -eq 0) { $python = @('py','-3.11') }
}
if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue)) {
  & python -c 'import sys; assert sys.version_info >= (3,9)' 2>$null
  if ($LASTEXITCODE -eq 0) { $python = @('python') }
}
if (-not $python) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw 'Python 3.11+ is missing and winget is unavailable. Install Python 3.11 from python.org, then retry.'
  }
  Write-Host 'Installing Python 3.11 with winget (may require confirmation)...'
  winget install --id Python.Python.3.11 --exact --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
  $python = @('py','-3.11')
}
if ($python.Count -eq 2) { & $python[0] $python[1] setup.py }
else { & $python[0] setup.py }
if ($LASTEXITCODE -ne 0) { throw 'Setup failed. Review the error above.' }
