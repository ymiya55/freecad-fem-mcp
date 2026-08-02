<# Compatibility entry point for Windows users. #>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $RepoRoot,
    [string] $McpConfigPath,
    [string] $ServerName,
    [switch] $SkipAddon,
    [switch] $SkipMcpConfig,
    [switch] $Force
)
$forward = @{}
if ($PSBoundParameters.ContainsKey("RepoRoot")) { $forward.RepoRoot = $RepoRoot }
if ($PSBoundParameters.ContainsKey("McpConfigPath")) { $forward.McpConfigPath = $McpConfigPath }
if ($PSBoundParameters.ContainsKey("ServerName")) { $forward.ServerName = $ServerName }
if ($SkipAddon) { $forward.SkipAddon = $true }
if ($SkipMcpConfig) { $forward.SkipMcpConfig = $true }
if ($Force) { $forward.Force = $true }
if ($WhatIfPreference) { $forward.WhatIf = $true }
& (Join-Path $PSScriptRoot "uninstall_windows.ps1") @forward
exit $LASTEXITCODE
