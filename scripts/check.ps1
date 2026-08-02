<# Compatibility entry point for Windows users. #>
[CmdletBinding()]
param(
    [string] $RepoRoot,
    [string] $McpConfigPath,
    [string] $ServerName,
    [switch] $Json,
    [switch] $SkipAddon,
    [switch] $SkipMcpConfig
)
$forward = @{}
if ($PSBoundParameters.ContainsKey("RepoRoot")) { $forward.RepoRoot = $RepoRoot }
if ($PSBoundParameters.ContainsKey("McpConfigPath")) { $forward.McpConfigPath = $McpConfigPath }
if ($PSBoundParameters.ContainsKey("ServerName")) { $forward.ServerName = $ServerName }
if ($Json) { $forward.Json = $true }
if ($SkipAddon) { $forward.SkipAddon = $true }
if ($SkipMcpConfig) { $forward.SkipMcpConfig = $true }
& (Join-Path $PSScriptRoot "check_windows.ps1") @forward
exit $LASTEXITCODE
