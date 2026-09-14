"""Anniversary (time-limited) type 7/8 augs."""

from __future__ import annotations

from typing import Iterable, TypeVar

from inventory_parser.slot2_augs.raidloot import AugCandidate

# Name marker for EQ anniversary gems (vendor event; not always available).
ANNIVERSARY_NAME_MARKER = "gem of distant echoes"

T = TypeVar("T", bound=AugCandidate)


def is_anniversary_aug(name: str | None) -> bool:
    """True when the item name is an anniversary Distant Echoes gem."""
    if not name:
        return False
    return ANNIVERSARY_NAME_MARKER in name.casefold()


def filter_anniversary_augs(
    augs: Iterable[T],
    *,
    include_anniversary: bool,
) -> list[T]:
    """Drop anniversary gems unless ``include_anniversary`` is true."""
    if include_anniversary:
        return list(augs)
    return [a for a in augs if not is_anniversary_aug(a.name)]
