"""EQGM Web FastAPI application."""

from __future__ import annotations

import base64
import re
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import limits
from app.cache_seed import configure_cache_dir, project_root, seed_disk_caches
from app.jobs import JobStore

# Point catalog I/O at repo cache/ before any generate (also re-run on startup).
configure_cache_dir()

# Engine imports (PYTHONPATH=src)
from inventory_parser import __version__
from inventory_parser.achievement_files import collect_achievement_paths
from inventory_parser.character_column_order import (
    ColumnRosterEntry,
    build_column_roster,
    paths_for_roster_removal,
    reset_tier_colors,
    save_character_column_order,
    save_tier_color,
    saved_character_column_order,
    tier_colors_are_custom,
)
from inventory_parser.eq_servers import server_display_name
from inventory_parser.excel_theme import tier_legend_entries
from inventory_parser.export_bundle import build_export_bundle, release_export_memory
from inventory_parser.html_export import write_team_html
from inventory_parser.missing_spells import (
    bindings_include_personas,
    discover_persona_bindings,
    split_input_paths,
)
from inventory_parser.output_paths import (
    default_export_prefix_from_input_paths,
    html_path_for_workbook,
    team_inventory_path,
)
from inventory_parser.package_data import asset_path
from inventory_parser.slot2_augs.build import report_progress
from inventory_parser.slot2_augs.weights import default_class_weights, sanitize_weight_map
from inventory_parser.slots import NON_VISIBLE_SLOTS, VISIBLE_SLOTS, SlotFilter
from inventory_parser.team_report import FolderCharacterChoice, discover_folder_character_choices

PRODUCT_WEBSITE_URL = "https://neclub.github.io/EQ-Gear-Management/"
SESSION_HEADER = "X-EQGM-Session"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\- ]+")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = _SAFE_NAME_RE.sub("_", base).strip(" .")
    if not cleaned.lower().endswith(".txt"):
        cleaned = f"{cleaned}.txt" if cleaned else "upload.txt"
    return cleaned[:180] or "upload.txt"


def _choice_summary(choice: FolderCharacterChoice) -> str:
    parts: list[str] = []
    if choice.inventory_paths:
        n = len(choice.inventory_paths)
        parts.append(f"{n} inventory" if n != 1 else "1 inventory")
    if choice.spell_paths:
        n = len(choice.spell_paths)
        parts.append(f"{n} MissingSpells" if n != 1 else "1 MissingSpells")
    if choice.achievement_paths:
        n = len(choice.achievement_paths)
        parts.append(f"{n} Achievements" if n != 1 else "1 Achievements")
    return ", ".join(parts) if parts else "No files"


def _class_abbr_from_choice(choice: FolderCharacterChoice) -> str | None:
    from inventory_parser.missing_spells import parse_missing_spells_filename

    for path in choice.spell_paths:
        parsed = parse_missing_spells_filename(path)
        if parsed is not None:
            return parsed[2]
    return None


def _choice_dict(choice: FolderCharacterChoice) -> dict:
    return {
        "character": choice.character,
        "server": choice.server,
        "serverDisplay": server_display_name(choice.server),
        "classAbbr": _class_abbr_from_choice(choice),
        "inventoryCount": len(choice.inventory_paths),
        "spellCount": len(choice.spell_paths),
        "achievementCount": len(choice.achievement_paths),
        "summary": _choice_summary(choice),
        "paths": [str(p) for p in choice.paths],
    }


def _roster_entry_dict(entry: ColumnRosterEntry) -> dict:
    return {
        "personaKey": entry.persona_key,
        "displayName": entry.display_name,
        "character": entry.character,
        "server": entry.server,
        "classAbbr": entry.class_abbr,
    }


def _public_error(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:500]


store = JobStore(Path(tempfile.gettempdir()) / "eqgm-web")
app = FastAPI(title="EQGM Web", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    configure_cache_dir()
    seed_disk_caches()


def _require_session(session_id: str | None) -> Any:
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session. Upload files first.")
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session expired. Upload files again.")
    return session


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.post("/api/session")
def create_session(request: Request) -> dict:
    session = store.create_session(_client_ip(request))
    return {"sessionId": session.id}


@app.get("/api/version")
def get_version() -> dict:
    logo = ""
    try:
        data = asset_path("eq-icon.png").read_bytes()
        logo = "data:image/png;base64," + base64.standard_b64encode(data).decode("ascii")
    except OSError:
        pass
    return {
        "version": __version__,
        "logoDataUri": logo,
        "websiteUrl": PRODUCT_WEBSITE_URL,
    }


@app.get("/api/prefs")
def get_prefs() -> dict:
    return {"lastEqFolder": None}


@app.get("/api/class-weights")
def class_weights(class_abbr: str | None = None, profile: str | None = None) -> dict:
    return default_class_weights(class_abbr, profile=profile)


@app.post("/api/upload")
async def upload_files(
    request: Request,
    files: list[UploadFile] = File(...),
    x_eqgm_session: str | None = Header(default=None, alias=SESSION_HEADER),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > limits.MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {limits.MAX_FILES}).",
        )

    session = store.get_session(x_eqgm_session) if x_eqgm_session else None
    if session is None:
        session = store.create_session(_client_ip(request))

    total = 0
    saved: list[str] = []
    for upload in files:
        raw_name = upload.filename or "upload.txt"
        if not raw_name.lower().endswith(limits.ALLOWED_SUFFIXES):
            raise HTTPException(
                status_code=400,
                detail=f"Only .txt EverQuest output files are allowed ({raw_name}).",
            )
        name = _safe_filename(raw_name)
        dest = session.upload_dir / name
        # Avoid clobber when same name uploaded twice
        if dest.exists():
            stem = dest.stem
            dest = session.upload_dir / f"{stem}_{len(saved)}{dest.suffix}"
        data = await upload.read()
        if len(data) > limits.MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"{name} exceeds {limits.MAX_FILE_BYTES // (1024 * 1024)} MB limit.",
            )
        total += len(data)
        if total > limits.MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="Total upload size too large.")
        dest.write_bytes(data)
        saved.append(str(dest.resolve()))

    # Merge into session path list (unique)
    existing = set(session.paths)
    for path in saved:
        if path not in existing:
            session.paths.append(path)
            existing.add(path)
    store.touch_session(session.id)

    choices = discover_folder_character_choices(session.upload_dir)
    if len(choices) > limits.MAX_CHARACTERS:
        # Still return choices; client can select a subset
        pass
    servers = sorted({c.server for c in choices}, key=str.casefold)
    return {
        "sessionId": session.id,
        "folder": str(session.upload_dir),
        "saved": saved,
        "paths": list(session.paths),
        "choices": [_choice_dict(c) for c in choices],
        "servers": [
            {"slug": slug, "label": server_display_name(slug)} for slug in servers
        ],
        "characterCount": len(choices),
        "maxCharacters": limits.MAX_CHARACTERS,
    }


class PathsBody(BaseModel):
    paths: list[str] = Field(default_factory=list)


@app.post("/api/split-paths")
def split_paths_api(body: PathsBody) -> dict:
    inv, spells, achievements = split_input_paths([Path(p) for p in body.paths])
    return {
        "inventory": [str(p) for p in inv],
        "spells": [str(p) for p in spells],
        "achievements": [str(p) for p in achievements],
    }


@app.post("/api/roster")
def build_roster_api(body: PathsBody) -> list[dict]:
    entries = build_column_roster(body.paths, saved_character_column_order())
    return [_roster_entry_dict(e) for e in entries]


class RosterOrderBody(BaseModel):
    personaKeys: list[str]


@app.post("/api/roster/order")
def save_roster_order_api(body: RosterOrderBody) -> dict:
    save_character_column_order(body.personaKeys)
    return {"ok": True}


class RemovalBody(BaseModel):
    removingKeys: list[str]
    roster: list[dict]
    paths: list[str]


@app.post("/api/roster/paths-for-removal")
def paths_for_removal_api(body: RemovalBody) -> list[str]:
    removing = [
        ColumnRosterEntry(
            persona_key=e["personaKey"],
            display_name=e["displayName"],
            character=e["character"],
            server=e["server"],
            class_abbr=e.get("classAbbr"),
        )
        for e in body.roster
        if e["personaKey"] in body.removingKeys
    ]
    full_roster = [
        ColumnRosterEntry(
            persona_key=e["personaKey"],
            display_name=e["displayName"],
            character=e["character"],
            server=e["server"],
            class_abbr=e.get("classAbbr"),
        )
        for e in body.roster
    ]
    drop = paths_for_roster_removal(removing, full_roster, body.paths)
    return sorted(drop)


@app.post("/api/spell-bindings")
def spell_bindings_api(body: PathsBody) -> dict:
    inv, spells, _ = split_input_paths([Path(p) for p in body.paths])
    discovery = discover_persona_bindings(inv, spell_paths=spells or None)
    spell_count = sum(1 for b in discovery.bindings if b.spell_path)
    return {
        "hasSpells": bool(spell_count),
        "spellCount": spell_count,
        "usePersonaLabel": bindings_include_personas(discovery.bindings),
        "warnings": list(discovery.warnings),
    }


@app.post("/api/achievement-info")
def achievement_info_api(body: PathsBody) -> dict:
    inv, _, achievements = split_input_paths([Path(p) for p in body.paths])
    discovered = collect_achievement_paths(inv, achievements or None)
    count = len(achievements) if achievements else len(discovered)
    return {"hasAchievements": bool(count), "achievementCount": count}


@app.get("/api/tier-legend")
def tier_legend_api() -> dict:
    rows = tier_legend_entries()
    return {
        "rows": rows,
        "isCustom": tier_colors_are_custom(),
        "visibleSlots": list(VISIBLE_SLOTS),
        "nonVisibleSlots": list(NON_VISIBLE_SLOTS),
    }


class TierColorBody(BaseModel):
    key: str
    value: str


@app.post("/api/tier-color")
def set_tier_color_api(body: TierColorBody) -> dict:
    colors = save_tier_color(body.key, body.value)
    return {
        "colors": colors,
        "isCustom": tier_colors_are_custom(colors),
        "rows": tier_legend_entries(),
    }


@app.post("/api/tier-colors/reset")
def reset_tier_colors_api() -> dict:
    colors = reset_tier_colors()
    return {
        "colors": colors,
        "isCustom": False,
        "rows": tier_legend_entries(),
    }


class GenerateBody(BaseModel):
    paths: list[str]
    slotFilter: str = "all"
    includeSpells: bool = False
    includeAchievements: bool = False
    includeSlot2: bool = True
    includeType5: bool = True
    includeType18: bool = True
    includeRaidBis: bool = True
    includeAnniversary: bool = False
    advancedWeights: bool = False
    sessionWeights: dict | None = None
    characterColumnOrder: list[str] | None = None
    tierColors: dict[str, str] | None = None


@app.post("/api/generate")
def generate_api(
    body: GenerateBody,
    request: Request,
    x_eqgm_session: str | None = Header(default=None, alias=SESSION_HEADER),
) -> dict:
    session = _require_session(x_eqgm_session)
    client_ip = _client_ip(request)
    err = store.try_acquire_generate(client_ip)
    if err:
        raise HTTPException(status_code=429, detail=err)

    # Validate paths belong to this session upload dir
    root = session.upload_dir.resolve()
    paths: list[Path] = []
    for raw in body.paths:
        path = Path(raw).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            store.release_generate()
            raise HTTPException(status_code=400, detail="Invalid file path.") from exc
        if not path.is_file():
            store.release_generate()
            raise HTTPException(status_code=400, detail=f"Missing file: {path.name}")
        paths.append(path)

    inv_paths, _, _ = split_input_paths(paths)
    if not inv_paths:
        store.release_generate()
        raise HTTPException(
            status_code=400,
            detail="Add at least one *-Inventory.txt file (MissingSpells alone is not enough).",
        )

    choices = discover_folder_character_choices(session.upload_dir)
    # Soft cap by unique characters in selection
    char_keys = {
        (c.character, c.server)
        for c in choices
        if any(str(p) in body.paths for p in c.paths)
    }
    if len(char_keys) > limits.MAX_CHARACTERS:
        store.release_generate()
        raise HTTPException(
            status_code=400,
            detail=f"Too many characters (max {limits.MAX_CHARACTERS}). Remove some and try again.",
        )

    job = store.create_job(session.id, client_ip=client_ip)
    config = body.model_dump()

    def work() -> None:
        job.status = "running"
        started = time.perf_counter()
        try:
            # Apply optional client tier colors for this generate
            if body.tierColors:
                for key, value in body.tierColors.items():
                    save_tier_color(key, value)

            def on_progress(payload: dict) -> None:
                job.progress = dict(payload)

            result = _generate_impl(paths, config, job, on_progress)
            job.result = result
            job.status = "done" if result.get("ok") else "error"
            if not result.get("ok"):
                job.error = result.get("error")
            if job.result is not None:
                job.result["elapsedSeconds"] = round(time.perf_counter() - started, 1)
        except Exception as exc:
            job.status = "error"
            job.error = _public_error(exc)
            job.result = {"ok": False, "error": job.error, "traceback": traceback.format_exc()[-2000:]}
        finally:
            release_export_memory()
            store.release_generate()

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True, "jobId": job.id}


def _generate_impl(
    paths: list[Path],
    config: dict,
    job: Any,
    on_progress,
) -> dict:
    raw_slots = (config.get("slotFilter") or "all").strip()
    slot_filter: SlotFilter = (
        raw_slots if raw_slots in ("all", "visible", "non_visible") else "all"
    )
    include_slot2 = bool(config.get("includeSlot2"))
    include_type5 = bool(config.get("includeType5"))
    include_type18 = bool(config.get("includeType18"))
    include_raid_bis = bool(config.get("includeRaidBis"))
    session_weights = None
    if include_slot2 and config.get("advancedWeights") and config.get("sessionWeights"):
        session_weights = sanitize_weight_map(config.get("sessionWeights") or {})

    prefix = default_export_prefix_from_input_paths(paths)
    assert job.output_dir is not None
    output_path = team_inventory_path(job.output_dir, prefix)
    html_target = html_path_for_workbook(output_path)

    try:
        bundle = build_export_bundle(
            paths,
            slot_filter=slot_filter,
            include_spells=bool(config.get("includeSpells")),
            include_achievements=bool(config.get("includeAchievements")),
            include_slot2=include_slot2,
            include_type5=include_type5,
            include_type18=include_type18,
            include_raid_bis=include_raid_bis,
            include_anniversary=bool(config.get("includeAnniversary")),
            session_weights=session_weights,
            on_progress=on_progress,
            character_column_order=config.get("characterColumnOrder") or None,
            include_item_cards=True,
        )
    except ValueError as exc:
        return {"ok": False, "error": _public_error(exc)}

    warnings = list(bundle.warnings)
    if include_slot2 or include_type5 or include_type18 or include_raid_bis:
        report_progress(on_progress, "Writing HTML…", 0.95, 1.0, 0, 1)

    html_saved = write_team_html(bundle, html_target)
    job.html_name = html_saved.name

    if include_slot2 or include_type5 or include_type18 or include_raid_bis:
        report_progress(on_progress, "Done", 0.95, 1.0, 1, 1)

    return {
        "ok": True,
        "jobId": job.id,
        "html": job.html_name,
        "warnings": warnings,
        "characterCount": len(bundle.team.characters),
        "downloadHtml": f"/api/jobs/{job.id}/download/html",
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    payload: dict[str, Any] = {
        "jobId": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
    }
    if job.status == "done" and job.result:
        payload["result"] = job.result
    elif job.status == "error":
        payload["result"] = job.result or {"ok": False, "error": job.error}
    return payload


@app.get("/api/jobs/{job_id}/download/{kind}")
def job_download(job_id: str, kind: str) -> FileResponse:
    job = store.get_job(job_id)
    if job is None or job.output_dir is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    if job.status != "done":
        raise HTTPException(status_code=409, detail="Report not ready.")
    if kind != "html":
        raise HTTPException(status_code=404, detail="Only HTML downloads are available.")
    if not job.html_name:
        raise HTTPException(status_code=404, detail="No HTML file for this job.")
    path = job.output_dir / job.html_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing.")
    headers = {
        "Content-Disposition": f'attachment; filename="{path.name}"',
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
        headers=headers,
    )


@app.post("/api/clear-cache")
def clear_cache_api() -> dict:
    # Public instance: do not wipe shared warmed caches.
    return {"ok": True, "deleted": [], "errors": [], "skipped": True}


web_dir = project_root() / "web"
if web_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
