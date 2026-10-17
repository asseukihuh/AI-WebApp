#!/usr/bin/env python3
"""Every global name referenced in ``scripts/*.py`` must resolve (catches imports lost in merges)."""

from __future__ import annotations

import ast
import builtins
import dis
import glob
import os
import types
import unittest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def _module_bindings(tree: ast.Module) -> set[str]:
    """Names bound at module level, including inside top-level if/try/with/for blocks."""
    bound: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.For, ast.With)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        bound.add(sub.id)
            elif isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.name:
                        bound.add(handler.name)
            for field in ("body", "orelse", "finalbody", "handlers"):
                children = getattr(node, field, None)
                if isinstance(children, list) and not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    visit([c for c in children if isinstance(c, ast.stmt)] or [
                        s for h in children if isinstance(h, ast.ExceptHandler) for s in h.body
                    ])

    visit(tree.body)
    return bound


def _referenced_globals(code: types.CodeType, *, module_level: bool) -> set[str]:
    names: set[str] = set()
    for instr in dis.get_instructions(code):
        if instr.opname == "LOAD_GLOBAL":
            names.add(str(instr.argval))
        elif instr.opname == "LOAD_NAME" and module_level:
            names.add(str(instr.argval))
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _referenced_globals(const, module_level=False)
    return names


def _stored_globals(code: types.CodeType) -> set[str]:
    names = {str(i.argval) for i in dis.get_instructions(code) if i.opname == "STORE_GLOBAL"}
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _stored_globals(const)
    return names


def undefined_names(path: str) -> set[str]:
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, path)
    code = compile(source, path, "exec")
    known = _module_bindings(tree) | _stored_globals(code) | set(dir(builtins))
    known |= {"__file__", "__name__", "__doc__", "__spec__", "__loader__", "__builtins__", "__annotations__"}
    return _referenced_globals(code, module_level=True) - known


class TestScriptNames(unittest.TestCase):
    def test_no_undefined_globals(self) -> None:
        failures = {}
        for path in sorted(glob.glob(os.path.join(SCRIPTS, "*.py"))):
            missing = undefined_names(path)
            if missing:
                failures[os.path.basename(path)] = sorted(missing)
        self.assertEqual(failures, {}, f"undefined names (missing imports?): {failures}")

    def test_serve_static_brand_profile_hooks(self) -> None:
        path = os.path.join(SCRIPTS, "serve-static.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "brand_profile"
            for alias in node.names
        }
        for name in ("analyze_brand", "apply_brand_profile_to_kit", "augment_ideogram_prompt", "playwright_available"):
            self.assertIn(name, imported)

    def test_detects_missing_import(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write("def f():\n    return analyze_brand()\n")
        try:
            self.assertEqual(undefined_names(handle.name), {"analyze_brand"})
        finally:
            os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main()
