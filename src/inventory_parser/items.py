"""Equipped item reference for export."""

from __future__ import annotations

from dataclasses import dataclass

EQRESOURCE_ITEM_URL = "https://items.eqresource.com/items.php?id={item_id}"


@dataclass(frozen=True)
class EquippedItem:
    name: str
    item_id: int
    is_evolver: bool = False
    resolved_tier: str | None = None

    @property
    def eqresource_url(self) -> str | None:
        if self.item_id <= 0:
            return None
        return EQRESOURCE_ITEM_URL.format(item_id=self.item_id)
