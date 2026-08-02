<#
.SYNOPSIS
    Remove the per-user FreeCAD FEM MCP addon and its MCP registration.

The command is deliberately conservative: an addon directory or MCP server
entry that does not carry the installer marker is left untouched unless
``-Force`` is supplied.  A backup is made before a configuration file is
changed.  Only the exact FreeCADFEMMCP directory and selected server key are
ever removed.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string] $RepoRoot = "",

    [Parameter()]
    [string] $McpConfigPath,

    [Parameter()]
    [string] $ServerName = "freecad-fem",

    [Parameter()]
    [switch] $SkipAddon,

    [Parameter()]
    [switch] $SkipMcpConfig,

    [Parameter()]
    [switch] $Force
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

function Backup-File {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $backup = "$Path.bak-$stamp"
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    Write-Host "Backed up $Path to $backup"
}

function Write-JsonAtomic {
    param([string] $Path, [object] $Value)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        $json = $Value | ConvertTo-Json -Depth 32
        $utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
        [System.IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, $utf8)
        Move-Item -LiteralPath $temp -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Remove-Addon {
    $destination = Join-Path (Join-Path (Get-ApplicationDataDirectory) "FreeCAD\v1-1\Mod") "FreeCADFEMMCP"
    if (-not (Test-Path -LiteralPath $destination)) {
        Write-Host "FreeCAD addon is not installed: $destination"
        return
    }
    $markerPath = Join-Path $destination ".freecad-fem-mcp-managed.json"
    $managed = $false
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        try {
            $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $managed = ((Get-PropertyValue $marker "managedBy") -eq "freecad-fem-mcp")
        }
        catch { $managed = $false }
    }
    if (-not $managed -and -not $Force) {
        throw "Refusing to remove unmarked addon directory: $destination (use -Force only after inspection)."
    }
    if ($PSCmdlet.ShouldProcess($destination, "Remove FreeCAD addon")) {
        Remove-Item -LiteralPath $destination -Recurse -Force
        Write-Host "Removed FreeCAD addon: $destination"
    }
}

function Test-OwnedServer {
    param([object] $Entry, [string] $Root)
    if ($null -eq $Entry) { return $false }
    $command = [string](Get-PropertyValue $Entry "command")
    $argsValue = Get-PropertyValue $Entry "args"
    if ($null -eq $argsValue) { return $false }
    $args = @($argsValue | ForEach-Object { [string]$_ })
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    return ($args -contains "freecad-fem-mcp") -and ($args -contains $fullRoot) -and ($command -in @("uv", "uv.exe", "freecad-fem-mcp", "freecad-fem-mcp.exe"))
}

function Remove-McpRegistration {
    param([string] $Root, [string] $ConfigPath)
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        Write-Host "MCP configuration is not present: $ConfigPath"
        return
    }
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "MCP configuration is not valid JSON; refusing to overwrite it: $ConfigPath. $($_.Exception.Message)"
    }
    if ($null -eq $config) { return }
    $servers = Get-PropertyValue $config "mcpServers"
    $entry = Get-PropertyValue $servers $ServerName
    if ($null -eq $entry) {
        Write-Host "MCP server '$ServerName' is not registered."
        return
    }
    $owned = Test-OwnedServer -Entry $entry -Root $Root
    if (-not $owned -and -not $Force) {
        throw "Refusing to remove MCP server '$ServerName' because it is not an installer-owned entry (use -Force only after inspection)."
    }
    if ($PSCmdlet.ShouldProcess($ConfigPath, "Remove MCP server '$ServerName'")) {
        Backup-File -Path $ConfigPath
        $servers.PSObject.Properties.Remove($ServerName)
        Write-JsonAtomic -Path $ConfigPath -Value $config
        Write-Host "Removed MCP server '$ServerName' from $ConfigPath"
    }
}

try {
    $root = [System.IO.Path]::GetFullPath($RepoRoot)
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "Repository root does not exist: $root" }
    if ([string]::IsNullOrWhiteSpace($McpConfigPath)) {
        $McpConfigPath = Join-Path (Get-ApplicationDataDirectory) "Claude\claude_desktop_config.json"
    }
    $McpConfigPath = [System.IO.Path]::GetFullPath($McpConfigPath)
    if (-not $SkipAddon) { Remove-Addon }
    if (-not $SkipMcpConfig) { Remove-McpRegistration -Root $root -ConfigPath $McpConfigPath }
    Write-Host "Uninstall complete."
}
catch {
    Write-Error $_
    exit 1
}
