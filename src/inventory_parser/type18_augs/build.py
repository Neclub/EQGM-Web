"""Build Type 18/19 catalog + class suggestions export."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from inventory_parser.slot2_augs.build import report_progress
from inventory_parser.type18_augs.catalog import (
    TYPE18_CATALOG_URL,
    TYPE19_CATALOG_URL,
    Type18CatalogEntry,
    Type18CatalogResult,
    fetch_type18_catalog,
)
from inventory_parser.type18_augs.categories import HEROIC_STAT_KEYS
from inventory_parser.type18_augs.suggestions import (
    ClassSuggestions,
    build_class_suggestions,
    cheat_sheet_source_url,
)

ProgressFn = Callable[[dict], None]

_PROGRESS_SEARCH = (0.05, 0.40)
_PROGRESS_HYDRATE = (0.40, 0.90)
_PROGRESS_SUGGEST = (0.90, 0.98)


@dataclass
class Type18Character:
    """Team character used for Type 18/19 suggestion owned checks."""

    key: str
    name: str
    display_name: str
    class_abbr: str
    owned_ids: set[int] = field(default_factory=set)
    owned_names: set[str] = field(default_factory=set)
    # item id / casefolded name → team gear slot when the aug is equipped
    equipped_locations_by_id: dict[int, str] = field(default_factory=dict)
    equipped_locations_by_name: dict[str, str] = field(default_factory=dict)


@dataclass
class Type18Export:
    entries: list[Type18CatalogEntry] = field(default_factory=list)
    suggestions: list[ClassSuggestions] = field(default_factory=list)
    characters: list[Type18Character] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched_at: str = ""
    from_cache: bool = False
    type18_url: str = TYPE18_CATALOG_URL
    type19_url: str = TYPE19_CATALOG_URL
    cheat_sheet_url: str = ""
    categories: list[str] = field(default_factory=list)
    team_class_abbrs: list[str] = field(default_factory=list)


def build_type18_export(
    *,
    allow_network: bool = True,
    force_refresh: bool = False,
    type18_html_by_page: dict[int, str] | None = None,
    type19_html_overrides: list[str] | None = None,
    item_html_by_id: dict[int, str] | None = None,
    catalog: Type18CatalogResult | None = None,
    class_abbrs: Iterable[str] | None = None,
    characters: Iterable[Type18Character] | None = None,
    on_progress: ProgressFn | None = None,
) -> Type18Export:
    """Fetch the Type 18/19 catalog and build per-class suggestions."""
    warnings: list[str] = []
    s0, s1 = _PROGRESS_SEARCH
    report_progress(on_progress, "Fetching from EQ Resource…", s0, s1, 0, 1)

    if catalog is None:
        def _hydrate_progress(done: int, total: int) -> None:
            h0, h1 = _PROGRESS_HYDRATE
            if total <= 0:
                report_progress(
                    on_progress, "Fetching item details from EQ Resource…", h0, h1, 1, 1
                )
            else:
                report_progress(
                    on_progress,
                    f"Fetching item details from EQ Resource… ({done}/{total})",
                    h0,
                    h1,
                    done,
                    total,
                )

        catalog = fetch_type18_catalog(
            force_refresh=force_refresh,
            allow_network=allow_network,
            type18_html_by_page=type18_html_by_page,
            type19_html_overrides=type19_html_overrides,
            item_html_by_id=item_html_by_id,
            on_progress=_hydrate_progress if on_progress else None,
        )
        h0, h1 = _PROGRESS_HYDRATE
        report_progress(
            on_progress, "Fetching item details from EQ Resource…", h0, h1, 1, 1
        )
    elif catalog.from_cache:
        report_progress(
            on_progress, "Using cached Type 18/19 catalog…", s0, s1, 1, 1
        )
    else:
        report_progress(on_progress, "Fetching from EQ Resource…", s0, s1, 1, 1)

    if catalog.warning:
        warnings.append(catalog.warning)

    char_list = list(characters or ())
    team_abbrs = [
        str(a).strip().upper() for a in (class_abbrs or []) if str(a).strip()
    ]
    if not team_abbrs:
        team_abbrs = [
            c.class_abbr for c in char_list if (c.class_abbr or "").strip()
        ]
    g0, g1 = _PROGRESS_SUGGEST
    report_progress(on_progress, "Building Type 18/19 class suggestions…", g0, g1, 0, 1)
    # Owned is applied per selected character in HTML/Excel, not baked into class rows.
    suggestions = build_class_suggestions(catalog.entries, class_abbrs=team_abbrs)
    report_progress(on_progress, "Building Type 18/19 class suggestions…", g0, g1, 1, 1)

    categories = sorted(
        {e.category for e in catalog.entries},
        key=lambda c: c.casefold(),
    )

    return Type18Export(
        entries=list(catalog.entries),
        suggestions=suggestions,
        characters=char_list,
        warnings=warnings,
        fetched_at=catalog.fetched_at,
        from_cache=catalog.from_cache,
        type18_url=catalog.type18_url,
        type19_url=catalog.type19_url,
        cheat_sheet_url=cheat_sheet_source_url(),
        categories=categories,
        team_class_abbrs=team_abbrs,
    )


# Re-export for callers/tests.
__all__ = [
    "HEROIC_STAT_KEYS",
    "Type18Character",
    "Type18Export",
    "build_type18_export",
]
