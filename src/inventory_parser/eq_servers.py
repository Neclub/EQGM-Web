"""EverQuest server slugs from /outputfile and eqlog_* log filenames.

Official short names (Daybreak): https://forums.everquest.com/threads/output-file-name-change.253743/
"""

from __future__ import annotations

import re
from pathlib import Path

# slug (lowercase) -> display name for export filenames
EQ_SERVER_DISPLAY_NAMES: dict[str, str] = {
    "agnarr": "Agnarr",
    "antonius": "Antonius Bayle",
    "bertox": "Bertoxxulous",
    "beta": "Beta",
    "brekt": "Brekt",
    "bristle": "Bristlebane",
    "cazic": "Cazic Thule",
    "coirnav": "Coirnav",
    "drinal": "Drinal",
    "erollisi": "Erollisi Marr",
    "fippy": "Fippy Darkpaw",
    "firiona": "Firiona Vie",
    "lockjaw": "Lockjaw",
    "luclin": "Luclin",
    "phinigel": "Phinigel",
    "povar": "Povar",
    "ragefire": "Ragefire",
    "rathe": "The Rathe",
    "test": "Test",
    "trakanon": "Trakanon",
    "tunare": "Tunare",
    "vox": "Vox",
    "xegony": "Xegony",
    "zek": "Zek",
}

_EQLOG_SERVER_RE = re.compile(r"^eqlog_[^_]+_(?P<server>[^_.]+)", re.IGNORECASE)


def server_display_name(server_slug: str) -> str:
    """Map log-file server slug to a display name for export files."""
    if not server_slug:
        return ""
    mapped = EQ_SERVER_DISPLAY_NAMES.get(server_slug.casefold())
    if mapped is not None:
        return mapped
    return server_slug[:1].upper() + server_slug[1:]


def server_slug_from_eqlog_filename(path: str | Path) -> str | None:
    """``eqlog_Neclub_bristle.txt`` -> ``bristle``."""
    m = _EQLOG_SERVER_RE.match(Path(path).name)
    if m is None:
        return None
    return m.group("server")
