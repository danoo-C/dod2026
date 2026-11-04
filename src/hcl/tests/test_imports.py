"""The hcl package uses absolute imports only (`from hcl.x import y`, never `from .x import y`).

It is installed in editable mode inside the container (`pip install -e src/hcl`,
see the Dockerfile), so `hcl` is importable from anywhere there.
"""

import ast
from pathlib import Path

import hcl

PACKAGE = Path(hcl.__file__).parent


def test_no_relative_imports():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                found.append(f"{path.relative_to(PACKAGE.parent)}:{node.lineno}")
    assert not found, "relative imports, use `from hcl... import ...` instead: " + ", ".join(found)


def test_the_package_is_the_mounted_source():
    # the editable install must point at the project, not at a copy in the image
    assert PACKAGE == Path("/work/src/hcl/hcl")
