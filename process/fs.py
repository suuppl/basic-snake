"""
process/fs.py — filesystem utilities

Keeps OS / CLI concerns out of compiler core.
"""

import os
from pathlib import Path


# =============================================================================
# BASIC FILE I/O
# =============================================================================

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f]


def write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


# =============================================================================
# DOS / CASE INSENSITIVE FILE HELPERS
# =============================================================================

def dos_name(path: str|Path) -> str:
    """
    Emulate DOS-style uppercase filenames.
    (used for compatibility with GW-BASIC workflows)
    """
    dir_, base = os.path.split(path)
    return os.path.join(dir_, base.upper()) if dir_ else base.upper()


def find_existing_ci(path: str):
    """
    Case-insensitive file lookup in directory.
    Returns actual file path if found, else None.
    """
    dir_ = os.path.dirname(path) or "."
    target = os.path.basename(path).upper()

    try:
        for e in os.listdir(dir_):
            if e.upper() == target:
                return os.path.join(dir_, e)
    except FileNotFoundError:
        return None

    return None