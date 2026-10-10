"""The Rust extension is built and importable."""


def test_core_extension_is_built():
    from signified import _core

    assert _core.__file__ is not None
    assert _core.__file__.endswith((".so", ".pyd"))
