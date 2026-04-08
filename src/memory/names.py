"""Mystical name registry — every delegated JINN gets a name at birth."""

from __future__ import annotations

import random

_NAMES: list[str] = [
    "Aether", "Alatar", "Azrael", "Calypso", "Chiron",
    "Circe", "Elara", "Galadriel", "Halcyon", "Kairos",
    "Lirael", "Morgana", "Nimue", "Oberon", "Selene",
    "Titania", "Zephyr", "Thorne", "Isolde", "Rune",
    "Vesper", "Solstice", "Onyx", "Obsidian", "Phantom",
    "Ember", "Nyx", "Riven", "Sable", "Wraith",
    "Cinder", "Dusk", "Hollow", "Shade", "Tempest",
    "Crimson", "Lotus", "Sage", "Ethereal", "Mystic",
    "Astral", "Eclipse", "Frost", "Glimmer", "Haze",
    "Indigo", "Jinx", "Kestrel", "Lumen", "Mirage",
    "Nebula", "Orion", "Pulse", "Quill", "Raven",
    "Seraph", "Talon", "Umbra",
]

_pool: list[str] = []


def assign_name() -> str:
    """Pick a unique mystical name per session (no repeats until pool exhausted)."""
    global _pool
    if not _pool:
        _pool = _NAMES.copy()
        random.shuffle(_pool)
    return _pool.pop()


def _reset() -> None:
    """Reset the name pool (for testing)."""
    global _pool
    _pool = []
