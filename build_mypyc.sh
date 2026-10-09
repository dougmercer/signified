#!/usr/bin/env bash
# Build signified's engine modules with mypyc, in place next to their sources.
#
# Requires a mypyc carrying mypyc-weakref.patch (native classes cannot be
# weakly referenced on Python 3.12+ without it; see mypyc/mypyc#1102):
#
#   uv pip install --python .venv/bin/python --no-binary mypy mypy setuptools
#   patch -d "$(.venv/bin/python -c 'import mypyc.codegen, os; print(os.path.dirname(mypyc.codegen.__file__))')" \
#       < mypyc-weakref.patch
#
# Usage: ./build_mypyc.sh [python]   (default: .venv/bin/python)
# Remove the built modules with: find src -name '*.so' -delete
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${1:-$ROOT/.venv/bin/python}"

EMITCLASS="$("$PY" -c 'import mypyc.codegen.emitclass as m; print(m.__file__)')"
if [[ "$EMITCLASS" != *.py ]] || ! grep -q "LOCAL PATCH" "$EMITCLASS"; then
    echo "mypyc is not patched (or is a compiled build that ignores source edits); see the header of $0" >&2
    exit 1
fi

cd "$ROOT/src"
find . -name "*.so" -delete
rm -rf build
"$PY" -m mypy signified/_reactive.py signified/_scheduler.py signified/_types.py signified/_functions.py signified/_mixin.py signified/_fields.py
# _mixin.py stays interpreted: it is the Python base class that gives native
# subclasses __weakref__, and it holds __getattr__/__setattr__, which mypyc
# forbids on native classes that inherit from a Python class.
"$PY" -m mypyc signified/_types.py signified/_scheduler.py signified/_reactive.py signified/_functions.py signified/_fields.py > /dev/null
find . -name "*.so" -not -path "./build/*" | sort
