from __future__ import annotations

import sys
import types


def install_pkg_resources_shim() -> str:
    """Keep PyFilesystem2 from importing deprecated ``pkg_resources`` on web.

    ``fs==2.4.16`` imports ``pkg_resources`` from its package initializer and
    opener registry. VaporTap only needs simfile's direct ``FS``/``OSFS`` path;
    it does not use third-party filesystem opener entry points. A tiny shim is
    therefore sufficient for the two APIs PyFilesystem2 touches during import.

    This is intentionally browser-only compatibility glue. Desktop VaporStep
    continues to use the normal installed dependency stack unchanged.
    """
    existing = sys.modules.get("pkg_resources")
    if existing is not None:
        return "existing"

    shim = types.ModuleType("pkg_resources")

    def declare_namespace(_name: str) -> None:
        return None

    def iter_entry_points(_group: str, _name: str | None = None):
        return ()

    shim.declare_namespace = declare_namespace  # type: ignore[attr-defined]
    shim.iter_entry_points = iter_entry_points  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = shim
    return "shim"


def ensure_decimal_runtime() -> str:
    """Provide a working ``decimal`` module under Pygbag/WASM.

    Pygbag's CPython runtime may expose a lightweight ``decimal.Decimal``
    placeholder so third-party wheels can import even when the C ``_decimal``
    extension is unavailable.  ``simfile`` genuinely constructs Decimal values
    for BPMs, stops, delays, warps, and offsets, so a placeholder is not enough.

    Prefer the runtime's normal decimal implementation when it works.  If it is
    only a stub, replace it with CPython's pure-Python ``_pydecimal`` module,
    which the web build stages alongside the application.
    """
    import decimal

    try:
        probe = decimal.Decimal("1.25")
        if float(probe) == 1.25:
            return "decimal"
    except Exception:
        pass

    try:
        import _pydecimal
    except Exception as exc:
        raise RuntimeError(
            "Pygbag provided a nonfunctional decimal.Decimal and the "
            "_pydecimal compatibility fallback could not be imported"
        ) from exc

    try:
        probe = _pydecimal.Decimal("1.25")
        if float(probe) != 1.25:
            raise ValueError(f"unexpected Decimal probe value: {probe!r}")
    except Exception as exc:
        raise RuntimeError("_pydecimal compatibility fallback is not functional") from exc

    # simfile imports Decimal/InvalidOperation from the public decimal module.
    # Swap the module before importing simfile so it sees CPython's complete
    # pure-Python implementation rather than Pygbag's placeholder.
    sys.modules["decimal"] = _pydecimal
    return "_pydecimal"
