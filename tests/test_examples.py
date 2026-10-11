"""Run the scripts shown on the docs' Examples page, so they keep working.

A script whose docstring has an "Expected output:" block must print exactly that.
"""

import ast
import re
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
# The page includes each file with `--8<-- "examples/..."`. A helper.py is
# imported by the script next to it, not run on its own.
INCLUDED = re.findall(r'--8<-- "(examples/[^"]+\.py)"', (ROOT / "docs" / "examples.md").read_text())
SCRIPTS = [ROOT / path for path in INCLUDED if not path.endswith("/helper.py")]


def expected_output(script: Path) -> str | None:
    docstring = ast.get_docstring(ast.parse(script.read_text())) or ""
    if "Expected output:" not in docstring:
        return None
    # The block is indented four spaces and ends at the next unindented line.
    lines = []
    for line in docstring.split("Expected output:", 1)[1].splitlines()[1:]:
        if line and not line.startswith("    "):
            break
        lines.append(line.removeprefix("    "))
    return "\n".join(lines).strip()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda script: str(script.relative_to(EXAMPLES)))
def test_example(script: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    if "watchdog" in script.read_text():
        pytest.importorskip("watchdog")
    monkeypatch.syspath_prepend(str(script.parent))
    runpy.run_path(str(script), run_name="__main__")
    expected = expected_output(script)
    if expected is not None:
        assert capsys.readouterr().out.strip() == expected
