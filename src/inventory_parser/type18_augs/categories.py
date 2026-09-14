"""Category keywords, anniversary markers, and type 18/19 classification."""

from __future__ import annotations

# Longest-first so "Dorsal Defense" wins over "Defense", "Assaulting" over "Assault".
CATEGORY_KEYWORDS: tuple[str, ...] = (
    "Dorsal Defense",
    "Ventral Defense",
    "Assaulting",
    "Defending",
    "Protecting",
    "Warding",
    "Enhancement",
    "Fortification",
    "Attacker",
    "Defender",
    "Defense",
    "Assault",
    "Casting",
    "Stealth",
    "Strategy",
    "Soothing",
    "Baraea",
    "Dire",
    "Hikma",
    "Qua",
)

ANNIVERSARY_NAME_MARKERS: tuple[str, ...] = (
    "jubilation",
    "enduring harmony",
)

HEROIC_STAT_KEYS: tuple[str, ...] = (
    "hstr",
    "hsta",
    "hint",
    "hwis",
    "hagi",
    "hdex",
    "hcha",
)

OTHER_CATEGORY = "Other"


def category_from_name(name: str | None) -> str:
    """Return the longest category keyword found in the item name."""
    text = (name or "").casefold()
    if not text:
        return OTHER_CATEGORY
    for keyword in CATEGORY_KEYWORDS:
        if keyword.casefold() in text:
            return keyword
    return OTHER_CATEGORY


def is_anniversary_aug(name: str | None) -> bool:
    """True when the name matches a Type 18/19 anniversary event marker."""
    text = (name or "").casefold()
    if not text:
        return False
    return any(marker in text for marker in ANNIVERSARY_NAME_MARKERS)


def classify_aug_type(aug_types: frozenset[int] | set[int] | None) -> int | None:
    """
    Classify as 18 or 19 from EQ Resource slot types.

    ``18, 19`` (or any listing that includes 18) → Type 18.
    ``19`` only → Type 19.
    """
    types = frozenset(aug_types or ())
    if 18 in types:
        return 18
    if 19 in types:
        return 19
    return None


def type_label(aug_types: frozenset[int] | set[int] | None) -> str:
    """
    Display label for the Type column.

    Dual ``18, 19`` → ``18/19`` (fits both holes).
    ``19`` only → ``19``.
    ``18`` only → ``18``.
    """
    types = frozenset(aug_types or ())
    has18 = 18 in types
    has19 = 19 in types
    if has18 and has19:
        return "18/19"
    if has19:
        return "19"
    if has18:
        return "18"
    return ""


def heroic_stat_sum(stats: dict[str, int] | None) -> int:
    src = stats or {}
    return sum(int(src.get(k, 0) or 0) for k in HEROIC_STAT_KEYS)


def stats_rank_key(stats: dict[str, int] | None, name: str | None) -> tuple:
    """Greatest stats first: HP, AC, heroic sum, then name."""
    src = stats or {}
    return (
        -int(src.get("hp", 0) or 0),
        -int(src.get("ac", 0) or 0),
        -heroic_stat_sum(src),
        (name or "").casefold(),
    )
