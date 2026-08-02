<# Run the dependency-free scanner and adversarial pytest suite on Windows. #>
[CmdletBinding()]
param(
    [string] $Python = "python",
    [switch] $SkipPytest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

& $Python (Join-Path $PSScriptRoot "security_scan.py") $root
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $SkipPytest) {
    & $Python -m pytest (Join-Path $root "tests\security") -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Host "Security checks passed."
