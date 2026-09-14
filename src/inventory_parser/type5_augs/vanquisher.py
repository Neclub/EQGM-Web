"""Vanquisher raid-achievement Type 5 aug catalog and short Expansion labels."""

from __future__ import annotations

from dataclasses import dataclass

ACHIEVEMENT_URL = "https://achievements.eqresource.com/achievements.php?id={achievement_id}"


@dataclass(frozen=True)
class VanquisherAug:
    """One expansion-wide Vanquisher Type 5 reward."""

    name: str
    item_id: int
    expansion: str
    abbreviation: str
    achievement_id: int

    @property
    def label(self) -> str:
        return f"Vanq {self.abbreviation}"

    @property
    def achievement_url(self) -> str:
        return ACHIEVEMENT_URL.format(achievement_id=self.achievement_id)

    @property
    def full_title(self) -> str:
        return f"Vanquisher of {self.expansion}"


# Started in Terror of Luclin; one reward per expansion Vanquisher meta.
VANQUISHER_AUGS: tuple[VanquisherAug, ...] = (
    VanquisherAug(
        name="Master's Curio",
        item_id=163995,
        expansion="Terror of Luclin",
        abbreviation="ToL",
        achievement_id=2901009,
    ),
    VanquisherAug(
        name="Divine Medallion",
        item_id=164196,
        expansion="Night of Shadows",
        abbreviation="NoS",
        achievement_id=3001009,
    ),
    VanquisherAug(
        name="Mythic Charm",
        item_id=151234,
        expansion="Laurion's Song",
        abbreviation="LS",
        achievement_id=31010009,
    ),
    VanquisherAug(
        name="Defiant Claw",
        item_id=151793,
        expansion="The Outer Brood",
        abbreviation="ToB",
        achievement_id=32010009,
    ),
    VanquisherAug(
        name="Arcane Tome",
        item_id=153972,
        expansion="Shattering of Ro",
        abbreviation="SoR",
        achievement_id=33010009,
    ),
)

_BY_ITEM_ID: dict[int, VanquisherAug] = {a.item_id: a for a in VANQUISHER_AUGS}
_BY_NAME: dict[str, VanquisherAug] = {a.name.casefold(): a for a in VANQUISHER_AUGS}


def lookup_vanquisher_aug(
    item_id: int | None = None,
    name: str | None = None,
) -> VanquisherAug | None:
    """Match a Vanquisher Type 5 aug by item id first, then casefolded name."""
    if item_id is not None and int(item_id) > 0:
        hit = _BY_ITEM_ID.get(int(item_id))
        if hit is not None:
            return hit
    key = (name or "").strip().casefold()
    if key:
        return _BY_NAME.get(key)
    return None


def vanquisher_label(
    item_id: int | None = None,
    name: str | None = None,
) -> tuple[str, str, str] | None:
    """Return ``(short_label, achievement_url, full_title)`` or ``None``."""
    aug = lookup_vanquisher_aug(item_id, name)
    if aug is None:
        return None
    return (aug.label, aug.achievement_url, aug.full_title)
