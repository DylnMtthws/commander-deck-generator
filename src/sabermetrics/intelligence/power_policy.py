"""Power-level policy over already-parsed game-changer configuration.

``configured_game_changer_names`` reads in-memory YAML documents only. It does
not open files, import a YAML library, or apply caller exceptions such as the
existing Sol Ring discard. Compatibility is with this project's published
``config/game_changers.yaml`` shapes, not a live lookup of official rules.
"""

from __future__ import annotations


def configured_game_changer_names(data: object) -> set[str]:
    """Return normalized game-changer names from parsed YAML data.

    Canonical input is a root mapping whose ``game_changers`` value is a list.
    A legacy top-level list is also accepted. Each entry may be a canonical
    ``{"card_name": str}`` mapping, a legacy ``{"name": str}`` mapping, or a
    plain string. A valid non-blank ``card_name`` wins; if it is missing or
    invalid, a valid non-blank legacy ``name`` is used when present.

    Names are ``strip().lower()``-normalized and deduplicated. ``None``,
    unrelated root metadata, unsupported root or collection shapes, and
    invalid entries (blank strings, non-strings, mappings without a usable
    name) are ignored. Non-string values are never stringified.

    Args:
        data: Already-parsed YAML document.

    Returns:
        Deduplicated set of normalized card names. Sol Ring is included when
        present; callers that keep the existing exception must ``discard``.
    """
    names: set[str] = set()
    for entry in _game_changer_entries(data):
        name = _entry_name(entry)
        if name is not None:
            names.add(name)
    return names


def _game_changer_entries(data: object) -> list[object]:
    """Return the configured entry list, or an empty list for unsupported data."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        raw = data.get("game_changers")
        if isinstance(raw, list):
            return raw
    return []


def _normalized_name(value: object) -> str | None:
    """Return a stripped lowercase name, or None when value is not a usable str."""
    if not isinstance(value, str):
        return None
    name = value.strip().lower()
    return name or None


def _entry_name(entry: object) -> str | None:
    """Resolve one list entry to a normalized name, or None if it is invalid."""
    if isinstance(entry, str):
        return _normalized_name(entry)
    if isinstance(entry, dict):
        canonical = _normalized_name(entry.get("card_name"))
        if canonical is not None:
            return canonical
        return _normalized_name(entry.get("name"))
    return None
