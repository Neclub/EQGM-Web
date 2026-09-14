"""Map craftable type 7/8 augs to their dropped empower components.

Containers (faded/diminished/nascent gems) are assumed available; only the
loot component is tracked for "Need to farm" notes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CraftComponent:
    """Dropped component combined into a faded/diminished/nascent gem container."""

    name: str
    item_id: int


# Affix substring (casefold) → component. Longer / more specific patterns first.
_AFFIX_COMPONENTS: tuple[tuple[str, CraftComponent], ...] = (
    (
        "unraveling order",
        CraftComponent("Unraveling Focus of Fortitude", 170818),
    ),
    (
        "phantasmal luclinite",
        CraftComponent("Otherworldly Focus of Fortitude", 159884),
    ),
    (
        "perpetual reverie",
        CraftComponent("Gallant Focus of Fortitude", 151983),
    ),
    (
        "luclinite ensanguined",
        CraftComponent("Ossified Bloodied Ore", 166327),
    ),
    (
        "of uprising",
        CraftComponent("Fortitude Focus of Uprising", 170458),
    ),
)


def craft_component_for_aug(name: str | None) -> CraftComponent | None:
    """Return the empower component for a finished aug name, if known."""
    if not name:
        return None
    folded = name.casefold()
    for affix, component in _AFFIX_COMPONENTS:
        if affix in folded:
            return component
    return None


def owns_craft_component(
    component: CraftComponent,
    *,
    owned_item_ids: set[int] | None = None,
    owned_item_names: set[str] | None = None,
) -> bool:
    """True when the dump contains the component (by ID or exact name)."""
    if owned_item_ids and component.item_id in owned_item_ids:
        return True
    if owned_item_names and component.name.casefold() in owned_item_names:
        return True
    return False
