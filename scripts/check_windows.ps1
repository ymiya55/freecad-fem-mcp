<#
.SYNOPSIS
    Check the local FreeCAD FEM MCP installation without changing files.

The exit code is 0 only when every requested component is present and points
to this repository.  Use ``-Json`` for CI or diagnostics tooling.
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string] $RepoRoot = "",

    [Parameter()]
    [string] $McpConfigPath,

    [Parameter()]
    [string] $ServerName = "freecad-fem",

    [Parameter()]
    [switch] $Json,

    [Parameter()]
    [switch] $SkipAddon,

    [Parameter()]
    [switch] $SkipMcpConfig
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

function Get-ApplicationDataDirectory {
    $appData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
    if ([string]::IsNullOrWhiteSpace($appData)) { throw "Unable to resolve ApplicationData." }
    return $appData
}

function Get-PropertyValue {
    param([object] $Object, [string] $Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Test-OwnedMcpEntry {
    param([object] $Entry, [string] $Root)
    if ($null -eq $Entry) { return $false }
    $command = [string](Get-PropertyValue $Entry "command")
    $argsValue = Get-PropertyValue $Entry "args"
    if ($null -eq $argsValue) { return $false }
    $args = @($argsValue | ForEach-Object { [string]$_ })
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    return ($args -contains "freecad-fem-mcp") -and ($args -contains $fullRoot) -and ($command -in @("uv", "uv.exe", "freecad-fem-mcp", "freecad-fem-mcp.exe"))
}

try {
    $root = [System.IO.Path]::GetFullPath($RepoRoot)
    if ([string]::IsNullOrWhiteSpace($McpConfigPath)) {
        $McpConfigPath = Join-Path (Get-ApplicationDataDirectory) "Claude\claude_desktop_config.json"
    }
    $McpConfigPath = [System.IO.Path]::GetFullPath($McpConfigPath)
    $report = [ordered]@{
        repository = $root
        addon = [ordered]@{ checked = (-not $SkipAddon); path = $null; installed = $false; managed = $false }
        mcpConfig = [ordered]@{ checked = (-not $SkipMcpConfig); path = $McpConfigPath; present = $false; validJson = $false; registered = $false; owned = $false }
        uv = [ordered]@{ available = $false; command = $null }
        ok = $true
        errors = @()
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $uv) { $report.uv.available = $true; $report.uv.command = $uv.Source }

    if (-not $SkipAddon) {
        $addonPath = Join-Path (Join-Path (Get-ApplicationDataDirectory) "FreeCAD\v1-1\Mod") "FreeCADFEMMCP"
        $report.addon.path = $addonPath
        $report.addon.installed = Test-Path -LiteralPath $addonPath -PathType Container
        $markerPath = Join-Path $addonPath ".freecad-fem-mcp-managed.json"
        if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
            try {
                $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $report.addon.managed = ((Get-PropertyValue $marker "managedBy") -eq "freecad-fem-mcp")
            }
            catch { $report.addon.managed = $false }
        }
        if (-not $report.addon.installed) { $report.errors += "FreeCAD addon is missing: $addonPath" }
        elseif (-not $report.addon.managed) { $report.errors += "FreeCAD addon is not marked as installer-managed: $addonPath" }
    }

    if (-not $SkipMcpConfig) {
        $report.mcpConfig.present = Test-Path -LiteralPath $McpConfigPath -PathType Leaf
        if (-not $report.mcpConfig.present) {
            $report.errors += "MCP configuration is missing: $McpConfigPath"
        }
        else {
            try {
                $config = Get-Content -LiteralPath $McpConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $report.mcpConfig.validJson = $true
                $servers = Get-PropertyValue $config "mcpServers"
                $entry = Get-PropertyValue $servers $ServerName
                $report.mcpConfig.registered = ($null -ne $entry)
                $report.mcpConfig.owned = Test-OwnedMcpEntry -Entry $entry -Root $root
                if ($null -eq $entry) { $report.errors += "MCP server '$ServerName' is not registered." }
                elseif (-not $report.mcpConfig.owned) { $report.errors += "MCP server '$ServerName' does not point to this repository." }
            }
            catch { $report.errors += "MCP configuration is not valid JSON: $McpConfigPath" }
        }
    }
    $report.ok = ($report.errors.Count -eq 0)
    if ($Json) {
        $report | ConvertTo-Json -Depth 12
    }
    else {
        if ($report.ok) { Write-Host "FreeCAD FEM MCP installation is healthy." }
        else {
            Write-Host "FreeCAD FEM MCP installation check failed:"
            $report.errors | ForEach-Object { Write-Host " - $_" }
        }
    }
    if (-not $report.ok) { exit 1 }
}
catch {
    if ($Json) {
        [pscustomobject]@{ ok = $false; errors = @($_.Exception.Message) } | ConvertTo-Json -Depth 8
    }
    else { Write-Error $_ }
    exit 1
}
