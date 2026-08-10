# Release guide

[Back to README](../../README.md)

Releases are created only after the public branch, native FreeCAD behavior, and
security boundary have been reviewed together. Do not tag a release merely
because the package metadata already contains its prospective version.

## Prepare the release

1. Confirm that the version matches in:
   - `pyproject.toml`;
   - `addon/FreeCADFEMMCP/package.xml`; and
   - `addon/FreeCADFEMMCP/version.py`.
2. Move the relevant entries from `CHANGELOG.md`'s `Unreleased` section to a
   versioned section with the release date.
3. Confirm that source, documentation, examples, and history contain no
   credentials, developer-local paths, or private author email addresses.
4. Synchronize the locked environment without changing the lock file:

   ```powershell
   uv sync --frozen --extra dev
   ```

5. Run the repository gates:

   ```powershell
   uv run --frozen --extra dev pytest
   uv run --frozen --extra dev ruff check .
   uv run --frozen --extra dev bandit -c .bandit -r src addon security scripts
   uv run --frozen --extra dev pip-audit --local --skip-editable
   uv run --frozen python scripts/security_scan.py
   uv build
   ```

6. Run the applicable portable `FreeCADCmd.exe` contracts, numerical
   benchmarks, and the GUI/MCP acceptance scenarios documented in
   [development.md](development.md).
7. Push the candidate commit and require CI, Security checks, and CodeQL to
   complete successfully on GitHub.

## Publish the release

After all gates pass:

1. create an annotated `v<version>` tag on the reviewed commit;
2. push the tag without moving or replacing an existing release tag;
3. create the GitHub Release from the matching changelog section;
4. attach only reproducible, reviewed artifacts; and
5. verify the source archive, wheel metadata, release notes, and compatibility
   statement from a clean checkout.

Release immutability should remain enabled so published tags and assets cannot
be silently replaced.
