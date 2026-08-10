# Security Policy

## Supported versions

This project is currently in its initial development phase. Before the first
public release, security fixes are provided on the current `main` branch. After
releases are published, only the latest release is supported.

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Latest release, once published | Yes |
| Older releases | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting for this repository:

https://github.com/ymiya55/freecad-fem-mcp/security/advisories/new

Include, where possible:

- the affected version or commit;
- the relevant MCP tool or FreeCAD operation;
- a minimal reproduction using non-sensitive files;
- the expected and observed security boundary;
- the potential impact; and
- any suggested mitigation.

Remove access tokens, local user names, private model data, and absolute local
paths from the report and its attachments. Please allow the maintainers time to
confirm and remediate the issue before public disclosure.

## Security boundary

The supported threat model and deliberately unavailable capabilities are
documented in the [security design](docs/developer/security.md). Reports that
rely on running FreeCAD or the MCP client under different operating-system
users, exposing the localhost bridge to a network, or bypassing the documented
installation model may be outside the supported boundary.
