"""Parse EQ Resource spell search HTML for catalog scraping."""

from __future__ import annotations

import re

from inventory_parser.missing_spells import strip_spell_rank

LEVEL_MIN = 121
LEVEL_MAX = 130

EXPANSION_BY_IMAGE: dict[str, str] = {
    "ls.jpg": "Laurion's Song",
    "tob.jpg": "The Outer Brood",
    "sor.jpg": "Shattering of Ro",
}

SPELL_LINK_RE = re.compile(
    r'<a\s+href=spells\.php\?id=(?P<id>\d+)[^>]*>(?P<name>[^<]+)</a>',
    re.I,
)
EXPANSION_IMG_RE = re.compile(r'<img\s+src="images/(?P<img>[^"]+)"', re.I)
RK_III_RE = re.compile(r"Rk\.?\s*III\b", re.I)


def catalog_key(level: int, spell_name: str) -> str:
    return f"{level}|{strip_spell_rank(spell_name).casefold()}"


def parse_spell_search_html(html: str) -> list[dict[str, object]]:
    """Regex-based parser (EQ Resource tables often omit closing </tr> tags)."""
    spells: list[dict[str, object]] = []
    current_level: int | None = None

    for chunk in re.split(r"<h2>\s*<center>\s*Level\s+(\d+)", html, flags=re.I):
        if not chunk:
            continue
        level_match = re.match(r"(\d+)", chunk)
        if level_match:
            current_level = int(level_match.group(1))
        if current_level is None or not (LEVEL_MIN <= current_level <= LEVEL_MAX):
            continue

        for row in re.split(r"<tr\b", chunk, flags=re.I)[1:]:
            link = SPELL_LINK_RE.search(row)
            if not link:
                continue
            name = link.group("name").strip()
            if not RK_III_RE.search(name):
                continue
            img_match = None
            for img in EXPANSION_IMG_RE.finditer(row):
                img_match = img
            if img_match is None:
                continue
            expansion = EXPANSION_BY_IMAGE.get(img_match.group("img"))
            if expansion is None:
                continue
            spells.append(
                {
                    "level": current_level,
                    "name": name,
                    "spell_id": int(link.group("id")),
                    "expansion": expansion,
                }
            )
    return spells
