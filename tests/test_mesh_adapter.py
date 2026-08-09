from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cinenode.engines.mesh import LocalMeshEngines


@pytest.mark.asyncio
async def test_generic_3d_cli_requires_and_verifies_a_real_mesh_file(tmp_path: Path):
    script = tmp_path / "write_mesh.py"
    script.write_text(
        "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('o cube\\nv 0 0 0\\nv 1 0 0\\nv 0 1 0\\nf 1 2 3\\n')\n",
        encoding="utf-8",
    )
    output = tmp_path / "mesh.obj"
    engines = LocalMeshEngines(
        {}, {},
        {"command": [sys.executable, str(script), "{{output}}"], "timeout_seconds": 30},
        {},
    )
    result = await engines.generate("local.generic_3d_cli", "cube", [], output, {})
    assert output.is_file()
    assert output.stat().st_size > 0
    assert result["engine"] == "local.generic_3d_cli"
    assert result["path"] == str(output.resolve())
