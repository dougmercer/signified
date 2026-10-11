"""Run the Python examples in the docs so they stay in sync with the library.

Blocks on one page share a namespace, so later examples can build on earlier
ones. Put `<!-- skip-test -->` on the line before a block to skip it. The
Playground's examples are files in docs/playground/, and each runs on its own.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
BLOCK = re.compile(r"^(<!-- skip-test -->\n)?```python\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The change log shows fragments of old APIs, so it is not run. The README is
# the PyPI page, so it is checked too.
PAGES = sorted(page for page in DOCS.glob("*.md") if page.name != "changes.md" and "```python" in page.read_text())
PAGES.append(DOCS.parent / "README.md")
PLAYGROUND_EXAMPLES = sorted((DOCS / "playground").glob("*.py"))


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.name)
def test_doc_examples(page: Path) -> None:
    text = page.read_text()
    namespace: dict[str, object] = {}
    for match in BLOCK.finditer(text):
        skip, code = match.groups()
        if skip:
            continue
        # Pad with blank lines so tracebacks point at the line in the page.
        padding = "\n" * text.count("\n", 0, match.start(2))
        exec(compile(padding + code, str(page), "exec"), namespace)


@pytest.mark.parametrize("example", PLAYGROUND_EXAMPLES, ids=lambda example: example.stem)
def test_playground_examples(example: Path) -> None:
    # An example file the page doesn't include would never show up in the menu.
    assert f'"docs/playground/{example.name}"' in (DOCS / "playground.md").read_text()
    exec(compile(example.read_text(), str(example), "exec"), {"__name__": "__main__"})
