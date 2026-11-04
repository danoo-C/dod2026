"""Import rules (docs/backend.md 5.1):

- absolute imports only (`from dod.x import y`, never `from .x import y`)
- inside the `dod` package, only `dod/hardware.py` imports `hcl`
- tests import only `hcl`'s public API and `hcl.testing`, nothing deeper

The checks read the source with `ast`; the checkers themselves are tested on
small snippets below, so a rule that silently stopped working would show up.
"""

import ast
from pathlib import Path

import hcl

import dod

PACKAGE = Path(dod.__file__).parent
TESTS = Path(__file__).parent
SEAM = PACKAGE / "hardware.py"
ALLOWED_IN_TESTS = {"hcl", "hcl.testing"}


def relative_imports(source: str) -> list[int]:
    """Lines with a relative import."""
    return [n.lineno for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.level > 0]


def hcl_modules(source: str) -> list[tuple[int, str]]:
    """Every hcl module the source imports, as (line, dotted name).

    `from hcl import Frame` counts as `hcl`; `from hcl import transport`
    reaches a submodule, so it counts as `hcl.transport`.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names if a.name == "hcl" or a.name.startswith("hcl.")]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "hcl":
                found += [(node.lineno, "hcl" if a.name in hcl.__all__ else f"hcl.{a.name}") for a in node.names]
            elif node.module.startswith("hcl."):
                found.append((node.lineno, node.module))
    return found


def sources(folder: Path):
    for path in sorted(folder.rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


# --- the rules, on the real code ----------------------------------------------


def test_no_relative_imports():
    found = [f"{path.relative_to(PACKAGE.parent)}:{line}"
             for folder in (PACKAGE, TESTS) for path, src in sources(folder) for line in relative_imports(src)]
    assert not found, "relative imports, use `from dod... import ...` instead: " + ", ".join(found)


def test_only_hardware_py_imports_hcl():
    found = [f"{path.relative_to(PACKAGE.parent)}:{line} imports {module}"
             for path, src in sources(PACKAGE) if path != SEAM for line, module in hcl_modules(src)]
    assert not found, "only dod/hardware.py may import hcl (docs/backend.md 5.1): " + ", ".join(found)


def test_hardware_py_uses_only_the_public_api():
    if not SEAM.exists():
        return  # comes in step 4
    found = [f"line {line}: {module}" for line, module in hcl_modules(SEAM.read_text(encoding="utf-8"))
             if module != "hcl"]
    assert not found, "dod/hardware.py may only use `hcl` itself: " + ", ".join(found)


def test_tests_use_only_the_public_api_and_hcl_testing():
    found = [f"{path.relative_to(PACKAGE.parent)}:{line} imports {module}"
             for path, src in sources(TESTS) for line, module in hcl_modules(src) if module not in ALLOWED_IN_TESTS]
    assert not found, "tests may import only `hcl` and `hcl.testing`: " + ", ".join(found)


def test_engine_tests_import_nothing_from_hcl():
    # the engine is tested without any hardware code (docs/backend.md 5.1)
    found = [f"{path.name}:{line} imports {module}"
             for path, src in sources(TESTS) if path.name.startswith("test_engine_")
             for line, module in hcl_modules(src)]
    assert not found, "engine tests must not import hcl: " + ", ".join(found)
    assert any(TESTS.glob("test_engine_*.py"))


def test_the_package_is_the_mounted_source():
    # the editable install must point at the project, not at a copy in the image
    assert PACKAGE == Path("/work/src/backend/dod")


# --- the checkers catch what they should --------------------------------------


def test_relative_imports_are_found():
    assert relative_imports("from .engine import loop\nfrom ..x import y\n") == [1, 2]
    assert relative_imports("from dod.engine import loop\nimport os\n") == []


def test_hcl_imports_are_found():
    assert hcl_modules("import hcl") == [(1, "hcl")]
    assert hcl_modules("from hcl import Frame, open_link") == [(1, "hcl"), (1, "hcl")]
    assert hcl_modules("import hcl.transport.sim") == [(1, "hcl.transport.sim")]
    assert hcl_modules("from hcl.transport.sim import SimTransport") == [(1, "hcl.transport.sim")]
    assert hcl_modules("from hcl import transport") == [(1, "hcl.transport")]
    assert hcl_modules("from hcl import testing") == [(1, "hcl.testing")]
    assert hcl_modules("from hcl.testing import sim_link") == [(1, "hcl.testing")]
    assert hcl_modules("def f():\n    import hcl\n") == [(2, "hcl")]  # also inside functions
    assert hcl_modules("import hclx\nfrom dod import hcl_view\n") == []
