# Security design

[Back to README](../../README.md)

## Threat model

The system does not trust the MCP client, model-generated input, names or metadata stored in an FCStd file, process logs, or file paths. FreeCAD and the MCP client are assumed to run as local applications under the same Windows user account.

The current release uses local STDIO for MCP. It does not expose an HTTP MCP listener, implement OAuth, or forward credentials to external services.

## Bridge boundary

- The Addon binds only to `127.0.0.1`.
- A cryptographically random token is generated for each FreeCAD launch.
- Token comparison uses constant-time comparison.
- Tokens are excluded from MCP results, logs, and normalized exceptions.
- The connection record is written atomically under the current user's LocalAppData.
- The recorded PID is checked and records for exited FreeCAD processes are rejected.
- Record refresh after transport failure is bounded to one attempt.
- NDJSON frames, queues, strings, arrays, images, and logs have explicit limits.
- Duplicate JSON keys, NaN/Infinity, unknown fields, and unknown method/action pairs are rejected.
- Every FreeCAD operation passes through typed parameters and a method allowlist.
- Gmsh and CalculiX logs are decoded with replacement, bounded, stripped of control characters, and redacted.

## Prohibited capabilities

- `eval` or `exec`
- `shell=True`
- dynamic imports selected by user input
- arbitrary Python, shell, or external commands
- arbitrary CalculiX INP fragments
- unrestricted file or environment enumeration
- bridge binding outside loopback
- legacy CalculiX solver routes

## File policy

Open and save operations are limited to normalized paths under configured allowed roots. The policy rejects:

- `..` traversal;
- UNC and Windows device paths;
- alternate data streams;
- escapes through symbolic links, junctions, or reparse points;
- disallowed file extensions.

Analysis changes stay in memory until an explicit save. Existing-file overwrite requires an explicit overwrite flag and a matching document revision.

## Mutation safety

Modifying operations are executed on the GUI thread and wrapped in FreeCAD undo transactions. Validation failures and rejected requests must not change the document revision. Public tool schemas are closed so that an MCP client cannot smuggle bridge actions or native property names through extra fields.

## Release gates

A release must pass:

- the full pytest suite;
- adversarial path, NDJSON, protocol, and fuzz tests;
- repository security scanning;
- Bandit with no unresolved Medium or High findings;
- dependency audit with no accepted known vulnerability outside policy;
- CodeQL and secret scanning gates;
- static checks against legacy solver and arbitrary-execution paths;
- relevant native FreeCAD integration and rejection tests.

Run the dependency-free repository scan with:

```powershell
python scripts/security_scan.py
```

Run the broader local security suite with:

```powershell
.\scripts\run_security_tests.ps1 -Python ".\.venv\Scripts\python.exe"
```

Never include the connection record or authentication token in bug reports, screenshots, fixtures, or CI artifacts.
