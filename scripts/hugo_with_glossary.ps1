# Invoke Hugo after refreshing all glossary data.
# Usage examples:
#   powershell -File scripts/hugo_with_glossary.ps1 server -D
#   powershell -File scripts/hugo_with_glossary.ps1 --minify

param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$HugoArgs
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

Write-Host "[INFO] Updating glossaries..." -ForegroundColor Cyan
python "$scriptDir/update_all_glossaries.py"
if ($LASTEXITCODE -ne 0) {
  Write-Host "[ERROR] Glossary update failed." -ForegroundColor Red
  exit $LASTEXITCODE
}

Write-Host "[INFO] Running hugo $($HugoArgs -join ' ')" -ForegroundColor Cyan
hugo @HugoArgs
exit $LASTEXITCODE
