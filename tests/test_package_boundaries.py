"""Mỗi package chỉ import những package nó được phép, đúng ranh giới container Level 2.

core không biết ai dùng nó. api, convert, index chỉ dựa vào core và không gọi lẫn nhau
(workflow gọi activity convert theo tên qua Temporal). cli chỉ nói chuyện với API qua HTTP,
lệnh api/worker import lười bên trong hàm.
"""

import ast
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[1] / "packages"

ALLOWED = {
    "core": {"core"},
    "api": {"core", "api"},
    "convert": {"core", "convert"},
    "index": {"core", "index"},
    "cli": set(),
}


def _ingest_imports(path: Path, top_level_only: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body if top_level_only else ast.walk(tree)
    found = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ingest."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[1] for a in node.names if a.name.startswith("ingest.")}
    return found


@pytest.mark.parametrize("pkg", sorted(ALLOWED))
def test_package_imports_stay_inside_boundary(pkg):
    files = list((PACKAGES / pkg / "src").rglob("*.py"))
    assert files, f"không thấy file nào trong packages/{pkg}"
    bad = {}
    for f in files:
        # cli được phép import lười trong hàm để chạy api/worker
        extra = _ingest_imports(f, top_level_only=pkg == "cli") - ALLOWED[pkg]
        if extra:
            bad[str(f.relative_to(PACKAGES))] = sorted(extra)
    assert not bad, f"import vượt ranh giới: {bad}"


def test_namespace_has_no_init():
    """`ingest` là namespace package chia cho nhiều distribution, không được có __init__.py."""
    assert not list(PACKAGES.glob("*/src/ingest/__init__.py"))
