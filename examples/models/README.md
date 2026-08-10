# Example geometry assets

These files contain geometry only. Use the MCP workflows in
[`docs/examples`](../../docs/examples/README.md) to add analyses, materials,
element definitions, supports, loads, meshes, and results.

Each model is supplied in two forms:

- `.FCStd`: preferred for FreeCAD FEM MCP; includes descriptive properties for
  likely support, load, shell, beam, and contact subelements;
- `.step`: neutral geometry for inspection or reconstruction.

Regenerate all assets with FreeCAD 1.1.x:

```powershell
& "$env:LOCALAPPDATA\Programs\FreeCAD 1.1\bin\FreeCADCmd.exe" `
  ".\scripts\generate_example_models.py" --pass --overwrite
```

Always confirm the stored `FaceN`, `EdgeN`, and `VertexN` hints with
`inspect_document` before creating an analysis. STEP import can renumber
subelements, so the hints belong to the FCStd version only.
