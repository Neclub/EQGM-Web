"""Data-driven role → class → slot overlay weights for aug scoring."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Mapping

from inventory_parser.slot2_augs.aug_stats import (
    ADVANCED_WEIGHT_ALWAYS,
    ADVANCED_WEIGHT_EXCLUDE,
    STAT_DISPLAY,
    STAT_KEYS,
)
from inventory_parser.slot2_augs.paths import appdata_dir
from inventory_parser.package_data import data_dir
from inventory_parser.slot2_augs.profiles import (
    CLASS_TO_PROFILE,
    FEET_HIGH_AC_CLASSES,
    PROFILE_LABELS,
    ProfileId,
)
from inventory_parser.slot2_augs.raidloot import AugCandidate
from inventory_parser.slots import EAR_REPORT_SLOTS

OVERRIDE_FILENAME = "weight_overrides.json"

# Per-generate session overrides (GUI advanced weights for a single character).
_session_absolute_weights: ContextVar[dict[str, float] | None] = ContextVar(
    "session_absolute_weights", default=None
)


def _appdata_root() -> Path:
    return appdata_dir()


def override_path() -> Path:
    return _appdata_root() / OVERRIDE_FILENAME


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_packaged() -> tuple[dict, dict, dict]:
    base = data_dir() / "weights"
    roles = _read_json(base / "roles.json")
    classes = _read_json(base / "classes.json")
    overlays = _read_json(base / "slot_overlays.json")
    return roles, classes, overlays


def _merge_weight_maps(
    base: Mapping[str, float], *deltas: Mapping[str, float] | None
) -> dict[str, float]:
    out: dict[str, float] = {k: float(v) for k, v in base.items() if k in STAT_KEYS}
    for delta in deltas:
        if not delta:
            continue
        for k, v in delta.items():
            if k not in STAT_KEYS:
                continue
            out[k] = float(out.get(k, 0.0)) + float(v)
    # Drop zero / near-zero weights so missing stats stay free.
    return {k: v for k, v in out.items() if abs(v) > 1e-9}


def _gear_slot_base(gear_slot: str) -> str:
    if gear_slot in EAR_REPORT_SLOTS or gear_slot.startswith("Ear"):
        return "Ear"
    if gear_slot.startswith("Wrist"):
        return "Wrist"
    if gear_slot.startswith("Fingers"):
        return "Fingers"
    return gear_slot


def _default_role_for_profile(profile: ProfileId) -> str:
    if profile == "int":
        return "pure_caster"
    if profile == "wis":
        return "priest"
    return "melee_dps"


@lru_cache(maxsize=1)
def _tables() -> tuple[dict, dict, dict, dict]:
    roles_doc, classes_doc, overlays_doc = _load_packaged()
    override = _read_json(override_path())
    return roles_doc, classes_doc, overlays_doc, override


def clear_weights_cache() -> None:
    """Test helper — drop cached JSON tables."""
    _tables.cache_clear()


def sanitize_weight_map(raw: Mapping[str, object] | None) -> dict[str, float]:
    if not raw:
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key not in STAT_KEYS:
            continue
        try:
            num = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if abs(num) > 1e-9:
            out[key] = num
    return out


@contextmanager
def session_absolute_weights(
    weights: Mapping[str, float] | None,
) -> Iterator[None]:
    """
    Temporarily replace role/class base weights for the current generate.

    Slot overlays (Feet AC-only, shield Secondary) still apply on top.
    """
    cleaned = sanitize_weight_map(weights) if weights else None
    token = _session_absolute_weights.set(cleaned or None)
    try:
        yield
    finally:
        _session_absolute_weights.reset(token)


def class_role(class_abbr: str | None) -> str | None:
    if not class_abbr:
        return None
    roles_doc, classes_doc, _overlays_doc, override = _tables()
    key = class_abbr.strip().upper()
    ov_classes = (override.get("classes") or {}) if isinstance(override.get("classes"), dict) else {}
    entry = ov_classes.get(key) or (classes_doc.get("classes") or {}).get(key)
    if isinstance(entry, dict) and entry.get("role"):
        return str(entry["role"])
    # Fallback from catalog profile map
    profile = CLASS_TO_PROFILE.get(key)
    if profile:
        return _default_role_for_profile(profile)
    _ = roles_doc
    return None


def resolve_weights(
    class_abbr: str | None,
    gear_slot: str,
    *,
    secondary_is_shield: bool = False,
    profile: ProfileId | None = None,
) -> dict[str, float]:
    """
    Effective weights = role base ⊕ class modifiers ⊕ slot overlays ⊕ AppData overrides.

    When :func:`session_absolute_weights` is active, that map replaces the
    role/class/AppData base; slot overlays still apply.
    """
    roles_doc, classes_doc, overlays_doc, override = _tables()
    roles = roles_doc.get("roles") or {}
    classes = classes_doc.get("classes") or {}

    key = (class_abbr or "").strip().upper() or None
    packaged = dict(classes.get(key) or {}) if key else {}
    ov_classes = override.get("classes") if isinstance(override.get("classes"), dict) else {}
    ov_entry = dict(ov_classes.get(key) or {}) if key else {}

    role_name = str(ov_entry.get("role") or packaged.get("role") or "")
    if not role_name:
        use_profile = profile or (CLASS_TO_PROFILE.get(key) if key else None) or "dex"
        role_name = _default_role_for_profile(use_profile)  # type: ignore[arg-type]

    session = _session_absolute_weights.get()
    if session is not None:
        base = dict(session)
        class_mods: dict[str, float] = {}
        flat: dict[str, float] = {}
    else:
        role_base = dict(roles.get(role_name) or {})
        ov_roles = override.get("roles") if isinstance(override.get("roles"), dict) else {}
        if role_name in ov_roles and isinstance(ov_roles[role_name], dict):
            # Role key overrides replace individual weights (not additive).
            role_base = {
                **role_base,
                **{k: float(v) for k, v in ov_roles[role_name].items()},
            }

        class_mods = {
            **(packaged.get("modifiers") or {}),
            **(ov_entry.get("modifiers") or {}),
        }
        base = role_base

        # Extra additive overrides: {"stat_overrides": {...}} or {"weights": {"WAR": {...}}}
        flat = {}
        if isinstance(override.get("stat_overrides"), dict):
            for k, v in override["stat_overrides"].items():
                flat[k] = float(v)
        if key and isinstance(override.get("weights"), dict):
            per = override["weights"].get(key)
            if isinstance(per, dict):
                for k, v in per.items():
                    flat[k] = float(flat.get(k, 0.0)) + float(v)

    slot_base = _gear_slot_base(gear_slot)
    overlay_mods: dict[str, float] = {}
    feet_ac_priority = False
    for overlay in overlays_doc.get("overlays") or []:
        if not isinstance(overlay, dict):
            continue
        slots = overlay.get("slots") or []
        if slot_base not in slots and gear_slot not in slots:
            continue
        classes_filter = overlay.get("classes")
        if classes_filter is not None:
            allowed = {c.upper() for c in classes_filter}
            if not key or key not in allowed:
                continue
        if overlay.get("require_shield") and not secondary_is_shield:
            continue
        if overlay.get("id") == "feet_high_ac":
            feet_ac_priority = True
        for k, v in (overlay.get("modifiers") or {}).items():
            overlay_mods[k] = float(overlay_mods.get(k, 0.0)) + float(v)

    merged = _merge_weight_maps(base, class_mods, overlay_mods, flat)
    if feet_ac_priority:
        return _apply_feet_ac_dominance(merged)
    return merged


def default_class_weights(
    class_abbr: str | None,
    *,
    profile: ProfileId | None = None,
) -> dict:
    """
    Class default weights for the Advanced GUI (Head slot — no Feet/shield overlay).

    Returns ``classAbbr``, ``profile``, ``profileLabel``, ``role``, and ``weights``.
    """
    key = (class_abbr or "").strip().upper() or None
    resolved_profile: ProfileId
    if profile:
        resolved_profile = profile
    elif key and key in CLASS_TO_PROFILE:
        resolved_profile = CLASS_TO_PROFILE[key]
    else:
        resolved_profile = "dex"

    role = class_role(key) or _default_role_for_profile(resolved_profile)
    weights = resolve_weights(key, "Head", profile=resolved_profile)
    # Stable UI order: STAT_KEYS, always include AC/HP/Mana plus focus stats
    # (HDex/HInt/HWis/SD); never Accuracy / Combat Effects / Shielding / Stun Resist.
    ordered: dict[str, float] = {}
    for k in STAT_KEYS:
        if k in ADVANCED_WEIGHT_EXCLUDE:
            continue
        if k in weights or k in ADVANCED_WEIGHT_ALWAYS:
            ordered[k] = float(weights.get(k, 0.0))
    for k in ADVANCED_WEIGHT_ALWAYS:
        ordered.setdefault(k, 0.0)
    return {
        "classAbbr": key,
        "profile": resolved_profile,
        "profileLabel": PROFILE_LABELS.get(resolved_profile, resolved_profile),
        "role": role,
        "weights": ordered,
        "labels": {k: STAT_DISPLAY.get(k, k) for k in ordered},
    }


def _apply_feet_ac_dominance(weights: dict[str, float]) -> dict[str, float]:
    """
    For Feet on high-AC classes, ranking is AC-only.

    Other role/class weights are dropped so focus/HP/ATK cannot outweigh AC.
    Equal-AC ties still break via ``rank_key`` (HP, then AC, then name).
    """
    return {"ac": float(weights.get("ac", 0.0))}


def score_aug(aug: AugCandidate, weights: Mapping[str, float]) -> float:
    stats = aug.effective_stats() if hasattr(aug, "effective_stats") else dict(aug.stats or {})
    total = 0.0
    for key, weight in weights.items():
        total += float(stats.get(key, 0)) * float(weight)
    return total


def rank_key(
    aug: AugCandidate,
    class_abbr: str | None,
    gear_slot: str,
    *,
    secondary_is_shield: bool = False,
    profile: ProfileId | None = None,
) -> tuple:
    """Sort key: higher score first, then HP, AC, name."""
    weights = resolve_weights(
        class_abbr,
        gear_slot,
        secondary_is_shield=secondary_is_shield,
        profile=profile or aug.profile,
    )
    score = score_aug(aug, weights)
    return (-score, -aug.hp, -aug.ac, aug.name.casefold())


def uses_feet_overlay(class_abbr: str | None) -> bool:
    """True when Feet high-AC overlay applies (same set as legacy FEET_HIGH_AC)."""
    if not class_abbr:
        return False
    key = class_abbr.strip().upper()
    # Prefer overlay JSON list when present.
    _roles_doc, _classes_doc, overlays_doc, _override = _tables()
    for overlay in overlays_doc.get("overlays") or []:
        if not isinstance(overlay, dict):
            continue
        if overlay.get("id") != "feet_high_ac":
            continue
        classes = overlay.get("classes") or []
        return key in {c.upper() for c in classes}
    return key in FEET_HIGH_AC_CLASSES
