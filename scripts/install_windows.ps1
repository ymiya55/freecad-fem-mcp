<#
.SYNOPSIS
    Install the FreeCAD FEM MCP workbench and register its local MCP command.

.DESCRIPTION
    The installer only writes below the current repository, the per-user
    FreeCAD Mod directory, and the explicitly selected MCP configuration file.
    Existing addon/configuration data is copied to a timestamped backup before
    it is changed.  No shell command is executed and no administrator rights
    are required.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string] $RepoRoot = "",

    [Parameter()]
    [string] $AddonSource,

    [Parameter()]
    [string] $McpConfigPath,

    [Parameter()]
    [string] $ServerName = "freecad-fem",

    [Parameter()]
    [string] $McpCommand = "uv",

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

function Resolve-ExistingDirectory {
    param([string] $Path, [string] $Label)
    $resolved = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label does not exist: $resolved"
    }
    return $resolved
}

function Get-ApplicationDataDirectory {
    $appData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
    if ([string]::IsNullOrWhiteSpace($appData)) {
        throw "Unable to resolve the per-user ApplicationData directory."
    }
    return $appData
}

function Get-PropertyValue {
    param([object] $Object, [string] $Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Set-PropertyValue {
    param([object] $Object, [string] $Name, [object] $Value)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
    else {
        $property.Value = $Value
    }
}

function Backup-File {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $backup = "$Path.bak-$stamp"
    Copy-Item -LiteralPath $Path -Destination $backup -Force
    Write-Host "Backed up $Path to $backup"
    return $backup
}

function Write-JsonAtomic {
    param([string] $Path, [object] $Value)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    $json = $Value | ConvertTo-Json -Depth 32
    try {
        $utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
        [System.IO.File]::WriteAllText($temp, $json + [Environment]::NewLine, $utf8)
        Move-Item -LiteralPath $temp -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }
    }
}

function Install-Addon {
    param([string] $Root, [string] $Source)
    # FreeCAD 1.1 isolates per-user data under the v1-1 profile.
    $modRoot = Join-Path (Get-ApplicationDataDirectory) "FreeCAD\v1-1\Mod"
    $destination = Join-Path $modRoot "FreeCADFEMMCP"
    if (-not (Test-Path -LiteralPath $modRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $modRoot -Force | Out-Null
    }
    if (Test-Path -LiteralPath $destination) {
        $marker = Join-Path $destination ".freecad-fem-mcp-managed.json"
        if (-not $Force -and -not (Test-Path -LiteralPath $marker -PathType Leaf)) {
            throw "Addon destination exists and is not managed by this installer: $destination (use -Force after taking a backup)."
        }
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
        # Backups must stay outside Mod: FreeCAD treats every Mod child as a
        # load candidate and would otherwise import stale bridge copies.
        $backupRoot = Join-Path (Split-Path -Parent $modRoot) "FreeCADFEMMCP-backups"
        $backup = Join-Path $backupRoot $stamp
        if ($PSCmdlet.ShouldProcess($destination, "Back up existing addon to $backup")) {
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            Copy-Item -LiteralPath $destination -Destination $backup -Recurse -Force
            Write-Host "Backed up existing addon to $backup"
        }
    }
    if ($PSCmdlet.ShouldProcess($destination, "Install FreeCAD addon")) {
        $staging = Join-Path $modRoot ("FreeCADFEMMCP.tmp-" + [Guid]::NewGuid().ToString("N"))
        try {
            Copy-Item -LiteralPath $Source -Destination $staging -Recurse -Force
            $metadata = [ordered]@{
                repository = $Root
                source = $Source
                installedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
                managedBy = "freecad-fem-mcp"
            }
            Write-JsonAtomic -Path (Join-Path $staging ".freecad-fem-mcp-managed.json") -Value ([pscustomobject] $metadata)
            if (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination -Recurse -Force
            }
            Move-Item -LiteralPath $staging -Destination $destination
        }
        finally {
            if (Test-Path -LiteralPath $staging) {
                Remove-Item -LiteralPath $staging -Recurse -Force
            }
        }
        Write-Host "Installed FreeCAD addon: $destination"
    }
}

function Install-McpConfig {
    param([string] $Root, [string] $ConfigPath)
    $config = [pscustomobject] @{}
    if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) {
        try {
            $raw = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                $config = $raw | ConvertFrom-Json
            }
        }
        catch {
            throw "MCP configuration is not valid JSON; refusing to overwrite it: $ConfigPath. $($_.Exception.Message)"
        }
        if ($null -eq $config) { $config = [pscustomobject] @{} }
    }
    $servers = Get-PropertyValue $config "mcpServers"
    if ($null -eq $servers) {
        $servers = [pscustomobject] @{}
        Set-PropertyValue $config "mcpServers" $servers
    }
    $args = @("run", "--project", ([System.IO.Path]::GetFullPath($Root)), "freecad-fem-mcp")
    $entry = [pscustomobject] @{ command = $McpCommand; args = $args }
    Set-PropertyValue $servers $ServerName $entry
    if ($PSCmdlet.ShouldProcess($ConfigPath, "Register MCP server '$ServerName'")) {
        if (Test-Path -LiteralPath $ConfigPath -PathType Leaf) { [void](Backup-File $ConfigPath) }
        Write-JsonAtomic -Path $ConfigPath -Value $config
        Write-Host "Registered MCP server '$ServerName' in $ConfigPath"
    }
}

$root = Resolve-ExistingDirectory -Path $RepoRoot -Label "Repository root"
if ([string]::IsNullOrWhiteSpace($AddonSource)) {
    $AddonSource = Join-Path $root "addon\FreeCADFEMMCP"
}
if (-not $SkipAddon) {
    $AddonSource = Resolve-ExistingDirectory -Path $AddonSource -Label "Addon source"
}
if ([string]::IsNullOrWhiteSpace($McpConfigPath)) {
    $McpConfigPath = Join-Path (Get-ApplicationDataDirectory) "Claude\claude_desktop_config.json"
}

try {
    if (-not $SkipAddon) { Install-Addon -Root $root -Source $AddonSource }
    if (-not $SkipMcpConfig) { Install-McpConfig -Root $root -ConfigPath ([System.IO.Path]::GetFullPath($McpConfigPath)) }
    Write-Host "Installation complete. Restart FreeCAD/your MCP client to load the addon and configuration."
}
catch {
    Write-Error $_
    exit 1
}
