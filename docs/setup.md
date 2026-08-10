# Setup

[日本語](setup.ja.md) · [Back to README](../README.md)

This page is for analysts installing FreeCAD FEM MCP on a Windows workstation. The installation has two cooperating parts:

- `FreeCADFEMMCP`, an Addon loaded by the FreeCAD GUI
- `freecad-fem-mcp`, a local MCP process started by your AI client

The supplied scripts install only into the current user profile and do not require administrator rights.

Choose one installation method:

- **Recommended:** follow steps 1–4 below and use `install.ps1` for the Addon.
- **Without the installer script:** go to [Manual installation](#manual-installation).

## 1. Check the engineering software

Install and start FreeCAD `>=1.1.3,<1.2`. In FreeCAD preferences, confirm that Gmsh and CalculiX are available to the FEM workbench.

Also install Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Check them from PowerShell:

```powershell
python --version
uv --version
```

## 2. Prepare the MCP server

Open PowerShell in the repository directory and install the runtime dependencies:

```powershell
uv sync
```

`uv sync --extra dev` is needed only when developing or running the test suite.

## 3. Install the FreeCAD Addon

Preview the file changes:

```powershell
.\scripts\install.ps1 -SkipMcpConfig -WhatIf
```

Install the Addon:

```powershell
.\scripts\install.ps1 -SkipMcpConfig
```

For FreeCAD 1.1, the Addon is installed at:

```text
%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP
```

An existing installer-managed Addon is backed up under `%APPDATA%\FreeCAD\v1-1\FreeCADFEMMCP-backups` before replacement. Restart FreeCAD after installation or update.

## 4. Register an MCP client

### Codex

Run these commands from the repository directory:

```powershell
codex mcp add freecad-fem -- uv run --project "$PWD" freecad-fem-mcp
codex mcp get freecad-fem
```

Restart Codex or start a new task after registration.

### Claude Desktop

The installer can safely back up and update the Claude Desktop JSON configuration:

```powershell
.\scripts\install.ps1 `
  -SkipAddon `
  -McpConfigPath "$env:APPDATA\Claude\claude_desktop_config.json"
```

Restart Claude Desktop completely after registration.

### Other STDIO MCP clients

Use a command and argument array equivalent to:

```json
{
  "command": "uv",
  "args": [
    "run",
    "--project",
    "C:\\absolute\\path\\to\\freecad-fem-mcp",
    "freecad-fem-mcp"
  ]
}
```

Use the absolute repository path. Do not combine the command and arguments into one shell string.

## Manual installation

Use this procedure when you do not want the supplied `install.ps1` script to copy the Addon or modify an MCP client configuration.

### 1. Prepare the Python environment

From PowerShell in the repository directory:

```powershell
uv sync
```

The MCP server remains in this repository and is launched with `uv run --project <repository path> freecad-fem-mcp`. It is not installed into FreeCAD's bundled Python.

### 2. Copy the FreeCAD Addon manually

Close FreeCAD first. Confirm that this source directory exists:

```text
<repository>\addon\FreeCADFEMMCP
```

The destination must be:

```text
%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP
```

If that destination already exists, stop and rename or back it up first. Do not merge different Addon versions. With no existing destination, the copy can be performed from the repository directory with:

```powershell
$freecadModRoot = Join-Path $env:APPDATA "FreeCAD\v1-1\Mod"
New-Item -ItemType Directory -Path $freecadModRoot -Force | Out-Null
Copy-Item -LiteralPath ".\addon\FreeCADFEMMCP" `
  -Destination $freecadModRoot `
  -Recurse
```

Verify the final layout. These files must be directly inside the destination folder, not inside a second nested `FreeCADFEMMCP` directory:

```text
FreeCADFEMMCP\Init.py
FreeCADFEMMCP\InitGui.py
FreeCADFEMMCP\package.xml
```

### 3. Register the MCP command manually

For Codex:

```powershell
codex mcp add freecad-fem -- uv run --project "C:\absolute\path\to\freecad-fem-mcp" freecad-fem-mcp
codex mcp get freecad-fem
```

For a client that uses JSON, add only the `freecad-fem` entry and preserve all existing servers:

```json
{
  "mcpServers": {
    "freecad-fem": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "C:\\absolute\\path\\to\\freecad-fem-mcp",
        "freecad-fem-mcp"
      ]
    }
  }
}
```

Back up the client's configuration before editing it. Use the schema required by that client; some clients use a key such as `servers` instead of `mcpServers`.

### 4. Restart and verify

Confirm the manually copied Addon entry point:

```powershell
Test-Path "$env:APPDATA\FreeCAD\v1-1\Mod\FreeCADFEMMCP\InitGui.py"
```

The expected result is `True`. A manual copy does not contain the installer's ownership marker, so `check.ps1` will report it as “not installer-managed.” This is expected and prevents the automated uninstaller from silently claiming a manually maintained directory.

Start FreeCAD, then restart the MCP client or begin a new task. Continue with the MCP connection check below.

## 5. Verify the installation

For an Addon installed by `install.ps1`, check the installation without assuming a particular MCP client configuration:

```powershell
.\scripts\check.ps1 -SkipMcpConfig
```

Then start FreeCAD, open a model, and ask the AI client:

```text
Use only the freecad-fem MCP. Run get_status and inspect_document,
then report the FreeCAD version, active document, and model objects.
Do not use shell commands.
```

A successful check reports the FreeCAD version, bridge status, and active document information.

## Opening models through MCP

The safest starting workflow is to open the model manually in FreeCAD. To use `open_model`, configure an allowed root with either:

- the `FREECAD_FEM_ALLOWED_ROOTS` environment variable, using semicolon-separated paths on Windows; or
- the FreeCAD parameter `User parameter:BaseApp/Preferences/Mod/FreeCADFEMMCP/AllowedRoots`.

Models already open in the FreeCAD GUI remain available even when no allowed root is configured.

## Updating

After updating the repository, run:

```powershell
uv sync
.\scripts\install.ps1 -SkipMcpConfig
```

Restart FreeCAD and start a new MCP client task so that both components use the updated version.

## Uninstalling

Preview removal of the installer-managed Addon:

```powershell
.\scripts\uninstall.ps1 -SkipMcpConfig -WhatIf
```

Remove it:

```powershell
.\scripts\uninstall.ps1 -SkipMcpConfig
```

Remove a Claude Desktop registration and the Addon together:

```powershell
.\scripts\uninstall.ps1 `
  -McpConfigPath "$env:APPDATA\Claude\claude_desktop_config.json"
```

For Codex, remove the registration with:

```powershell
codex mcp remove freecad-fem
```

The uninstaller does not remove FreeCAD, Python, uv, Gmsh, CalculiX, analysis models, or Addon backups.

A manually copied Addon is intentionally not installer-managed. Inspect and back up the exact `%APPDATA%\FreeCAD\v1-1\Mod\FreeCADFEMMCP` directory before removing it manually. Do not remove the surrounding `Mod` directory or other Addons.

If setup does not complete, continue with [Troubleshooting](troubleshooting.md).
