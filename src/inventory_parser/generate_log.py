"""Overwrite a single last-generate log under %LOCALAPPDATA%\\EQGM\\."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from inventory_parser import APP_NAME_SHORT, __version__
from inventory_parser import character_column_order as _settings

LOG_FILENAME = "last_report.log"


def last_report_log_path() -> Path:
    return _settings.settings_path().parent / LOG_FILENAME


def write_last_report_log(
    *,
    source: str,
    config: dict | None = None,
    result: dict | None = None,
    traceback_text: str | None = None,
    elapsed_seconds: float | None = None,
) -> Path | None:
    """Replace last_report.log with this run. Failures to write are ignored."""
    try:
        path = last_report_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = format_last_report_log(
            source=source,
            config=config or {},
            result=result,
            traceback_text=traceback_text,
            elapsed_seconds=elapsed_seconds,
        )
        tmp = path.with_name(f"{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return path
    except OSError:
        return None


def format_last_report_log(
    *,
    source: str,
    config: dict,
    result: dict | None,
    traceback_text: str | None,
    elapsed_seconds: float | None,
) -> str:
    ok = bool(result and result.get("ok"))
    error = ""
    if result and not result.get("ok"):
        error = str(result.get("error") or "").strip()
    if traceback_text and not error:
        error = "Export failed."
    status = "ok" if ok and not traceback_text else "failed"
    elapsed = result.get("elapsedSeconds") if result else None
    if elapsed is None:
        elapsed = elapsed_seconds
    elapsed_s = f"{elapsed}s" if elapsed is not None else "—"
    characters = result.get("characterCount") if result else None
    if characters is None:
        order = config.get("characterColumnOrder") or []
        characters = len(order) if order else "—"

    lines = [
        f"{APP_NAME_SHORT} last generated report",
        "==========================",
        f"Time: {_now_stamp()}",
        f"Version: {__version__}",
        f"Source: {source or '—'}",
        f"Status: {status}",
        f"Elapsed: {elapsed_s}",
        f"Characters: {characters}",
        "",
        "Output",
        "------",
        f"Excel: {_result_path(result, 'xlsx')}",
        f"HTML: {_result_path(result, 'html')}",
        f"Format: {_output_format(config, result)}",
        "",
        "Options",
        "-------",
        f"Spells: {_yesno(config.get('includeSpells'))}",
        f"Achievements: {_yesno(config.get('includeAchievements'))}",
        f"Type 7/8 Augs: {_yesno(config.get('includeSlot2'))}",
        f"Type 5 Augs: {_yesno(config.get('includeType5'))}",
        f"Type 18/19 Augs: {_yesno(config.get('includeType18'))}",
        f"Raid BiS: {_yesno(config.get('includeRaidBis'))}",
        f"Anniversary augs: {_yesno(config.get('includeAnniversary'))}",
        f"Advanced weights: {_advanced_weights(config)}",
        "",
        "Input files",
        "-----------",
        *_path_block(config.get("paths")),
        "",
        "Roster order",
        "------------",
        *_path_block(config.get("characterColumnOrder")),
        "",
        "Warnings",
        "--------",
        *_path_block((result or {}).get("warnings")),
        "",
        "Error",
        "-----",
        error or "(none)",
    ]
    if traceback_text and traceback_text.strip():
        lines.extend(["", "Traceback", "---------", traceback_text.strip()])
    lines.append("")
    return "\n".join(lines)


def _now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _yesno(value: object) -> str:
    return "yes" if value else "no"


def _output_format(config: dict, result: dict | None) -> str:
    fmt = str(config.get("outputFormat") or "").strip()
    if fmt:
        return fmt
    if config.get("alsoHtml"):
        return "both"
    has_xlsx = bool(result and result.get("xlsx"))
    has_html = bool(result and result.get("html"))
    if has_xlsx and has_html:
        return "both"
    if has_html:
        return "html"
    if has_xlsx:
        return "excel"
    return "—"


def _advanced_weights(config: dict) -> str:
    if not config.get("advancedWeights"):
        return "no"
    weights = config.get("sessionWeights") or {}
    n = len(weights) if isinstance(weights, dict) else 0
    return f"yes ({n} stats)" if n else "yes"


def _result_path(result: dict | None, key: str) -> str:
    if not result:
        return "(none)"
    value = result.get(key)
    return str(value) if value else "(none)"


def _path_block(values: object) -> list[str]:
    if not values:
        return ["(none)"]
    if isinstance(values, str):
        text = values.strip()
        return [text] if text else ["(none)"]
    lines = [str(item).strip() for item in values if str(item).strip()]
    return lines or ["(none)"]
