<# Compatibility entry point for Windows users. #>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $RepoRoot,
    [string] $AddonSource,
    [string] $McpConfigPath,
    [string] $ServerName,
    [string] $McpCommand,
    [switch] $SkipAddon,
    [switch] $SkipMcpConfig,
    [switch] $Force
)
$forward = @{}
if ($PSBoundParameters.ContainsKey("RepoRoot")) { $forward.RepoRoot = $RepoRoot }
if ($PSBoundParameters.ContainsKey("AddonSource")) { $forward.AddonSource = $AddonSource }
if ($PSBoundParameters.ContainsKey("McpConfigPath")) { $forward.McpConfigPath = $McpConfigPath }
if ($PSBoundParameters.ContainsKey("ServerName")) { $forward.ServerName = $ServerName }
if ($PSBoundParameters.ContainsKey("McpCommand")) { $forward.McpCommand = $McpCommand }
if ($SkipAddon) { $forward.SkipAddon = $true }
if ($SkipMcpConfig) { $forward.SkipMcpConfig = $true }
if ($Force) { $forward.Force = $true }
if ($WhatIfPreference) { $forward.WhatIf = $true }
& (Join-Path $PSScriptRoot "install_windows.ps1") @forward
exit $LASTEXITCODE
