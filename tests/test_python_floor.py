"""Guards for the Python version pyproject declares (>=3.11).

A developer on 3.13 happily accepts syntax 3.11 rejects, so the floor has to be
checked explicitly. This test exists because it already bit once: the ASCII-only
pass escaped CJK inside two f-string *expressions*, and PEP 701 only allowed a
backslash there from 3.12.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BACKSLASH = chr(92)


def declared_floor():
    text = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    m = re.search(r'requires-python\s*=\s*"[>=~!]*([0-9]+)\.([0-9]+)', text)
    assert m, 'requires-python not found in pyproject.toml'
    return int(m.group(1)), int(m.group(2))


def source_files():
    out = []
    for pattern in ('*.py', 'tests/*.py', 'scripts/*.py'):
        out.extend(sorted(REPO.glob(pattern)))
    return out


def test_no_backslash_inside_an_fstring_expression():
    """`f"{'\\u4e2d'}"` is a SyntaxError before 3.12.

    ast.parse(feature_version=...) does not model this rule, so the replacement
    fields are inspected directly. Escaping belongs in the literal text, never
    in the expression -- hoist the value into a variable instead.
    """
    offenders = []
    for path in source_files():
        src = path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            for part in node.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                segment = ast.get_source_segment(src, part) or ''
                if BACKSLASH in segment:
                    offenders.append(
                        f'{path.relative_to(REPO)}:{part.lineno}  {{{segment[:70]}}}')
    assert not offenders, (
        'these f-string expressions contain a backslash, which Python '
        f'{declared_floor()[0]}.{declared_floor()[1]} (the declared floor) '
        'rejects with a SyntaxError:\n  ' + '\n  '.join(offenders)
    )


@pytest.mark.skipif(sys.version_info >= (3, 12),
                    reason='only meaningful on an interpreter below 3.12')
def test_running_interpreter_is_at_or_above_the_floor():
    floor = declared_floor()
    assert sys.version_info[:2] >= floor
