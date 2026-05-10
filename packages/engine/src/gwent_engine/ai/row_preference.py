from __future__ import annotations

from gwent_engine.core import Row


def row_preference(row: Row) -> int:
    if row == Row.CLOSE:
        return 3
    if row == Row.RANGED:
        return 2
    return 1
