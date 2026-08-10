# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Typed MCP tools for native FreeCAD 1.1.x FEM analysis workflows.
- Native static, nonlinear static, frequency, and linear buckling analysis paths.
- Solid, shell, membrane, beam, and truss element workflows supported by native
  FreeCAD objects and CalculiX writers.
- Native materials, supports, loads, connections, meshing, validation, solving,
  result inspection, GUI display, and capture operations.
- Bounded FreeCAD tree-object show, hide, isolate, show-all, and hide-all
  controls for report-ready mesh and result captures.
- Authenticated loopback bridge with bounded input, output, file, process, and
  document-mutation policies.
- Portable FreeCAD contract tests, smoke tests, numerical benchmarks, and
  geometry-only example models.

### Security

- Closed public schemas and bridge allowlists reject arbitrary Python, shell,
  CalculiX input, native-property, and unrestricted filesystem escape routes.
- CI includes dependency auditing, static security checks, secret scanning, and
  CodeQL configuration.
