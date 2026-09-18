"""Variants — one overlay on the live extraction config per hypothesis.

Tuning extraction means changing three things: settings (`text_pass_min_items`,
tile grid, …), the prompt constants, and the plan-type specs (category guidance,
`prefer_vision`). A variant is a JSON file that overlays all three, applied
around a single extraction and then fully undone.

Restoration is the whole safety story here. `apply()` mutates PROCESS-GLOBAL
state — the same `settings` object and the same registry the API serves from —
so a variant that leaks would silently corrupt every later run in the process
(and, since the bench runs inside the dev API, the app itself). Everything is
restored in a `finally`, including when the body raises and including when the
overlay itself fails halfway through. It is NOT thread-safe: the runner applies
variants serially, by design.
"""
import copy
import glob
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.config import settings
from app.eval.corpus import corpus_dir
from app.services.extraction import prompts as prompts_module
from app.services.extraction import registry

# The empty overlay: extraction exactly as the product runs it. Reserved id —
# every comparison is ultimately against this.
BASELINE_ID = "baseline"

_SPEC_FIELDS = set(registry.PlanTypeSpec.model_fields) - {"key", "categories"}
_CATEGORY_FIELDS = set(registry.BomCategory.model_fields) - {"key"}


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    description: Optional[str] = None
    settings: dict = field(default_factory=dict)
    prompts: dict = field(default_factory=dict)
    spec_overrides: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "settings": dict(self.settings),
            "prompts": dict(self.prompts),
            "spec_overrides": copy.deepcopy(self.spec_overrides),
        }


def variants_dir() -> str:
    return os.path.join(corpus_dir(), "variants")


def _baseline() -> Variant:
    return Variant(
        id=BASELINE_ID,
        label="Baseline",
        description="Extraction exactly as the product runs it — no overrides.",
    )


def _from_dict(raw: dict, source: str) -> Variant:
    vid = str(raw.get("id") or "").strip()
    if not vid:
        raise ValueError("Variant in {} has no id".format(source))
    return Variant(
        id=vid,
        label=str(raw.get("label") or vid),
        description=(str(raw["description"]) if raw.get("description") else None),
        settings=dict(raw.get("settings") or {}),
        prompts=dict(raw.get("prompts") or {}),
        spec_overrides=dict(raw.get("spec_overrides") or {}),
    )


def load_variants() -> List[Variant]:
    """Every variant on disk, baseline first. Never raises on a missing corpus."""
    found: List[Variant] = []
    directory = variants_dir()
    if os.path.isdir(directory):
        for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, ValueError):
                # A broken variant file must not take the whole list down; the
                # CLI reports it through validate_variant on the ones that load.
                continue
            if isinstance(raw, dict):
                try:
                    found.append(_from_dict(raw, path))
                except ValueError:
                    continue
    if not any(v.id == BASELINE_ID for v in found):
        found.insert(0, _baseline())
    else:
        found.sort(key=lambda v: (v.id != BASELINE_ID, v.id))
    return found


def get_variant(vid: str) -> Variant:
    for variant in load_variants():
        if variant.id == vid:
            return variant
    raise KeyError("Unknown variant '{}'".format(vid))


def validate_variant(variant: Variant) -> List[str]:
    """Problems that would make `apply()` raise — reported before a run burns money."""
    problems: List[str] = []
    for key in variant.settings:
        if not hasattr(settings, key):
            problems.append("settings.{}: not a known setting".format(key))
    for name in variant.prompts:
        if not hasattr(prompts_module, name):
            problems.append("prompts.{}: not a constant in extraction.prompts".format(name))
        elif not isinstance(getattr(prompts_module, name), str):
            problems.append("prompts.{}: not a string constant".format(name))
    for plan_type, overrides in (variant.spec_overrides or {}).items():
        spec = registry.get(plan_type)
        if spec is None:
            problems.append("spec_overrides.{}: plan type is not registered".format(plan_type))
            continue
        if not isinstance(overrides, dict):
            problems.append("spec_overrides.{}: expected an object".format(plan_type))
            continue
        for key, value in overrides.items():
            if key == "categories":
                if not isinstance(value, dict):
                    problems.append("spec_overrides.{}.categories: expected an object".format(plan_type))
                    continue
                for cat_key, cat_overrides in value.items():
                    if spec.category(cat_key) is None:
                        problems.append(
                            "spec_overrides.{}.categories.{}: not a category of this plan type".format(
                                plan_type, cat_key
                            )
                        )
                        continue
                    for field_name in (cat_overrides or {}):
                        if field_name not in _CATEGORY_FIELDS:
                            problems.append(
                                "spec_overrides.{}.categories.{}.{}: not a BomCategory field".format(
                                    plan_type, cat_key, field_name
                                )
                            )
            elif key not in _SPEC_FIELDS:
                problems.append("spec_overrides.{}.{}: not a PlanTypeSpec field".format(plan_type, key))
    return problems


def _coerce(current, value):
    """Keep a JSON `"8"` from turning an int setting into a string."""
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, int) and not isinstance(value, bool) and isinstance(value, (str, float, int)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if isinstance(current, float) and isinstance(value, (str, int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _overlay_spec(spec: registry.PlanTypeSpec, overrides: dict) -> registry.PlanTypeSpec:
    """A DEEP COPY of the spec with the overrides applied — never mutate the original."""
    patched = spec.model_copy(deep=True)
    for key, value in (overrides or {}).items():
        if key == "categories":
            for cat_key, cat_overrides in (value or {}).items():
                category = patched.category(cat_key)
                if category is None:
                    raise ValueError(
                        "Variant overrides unknown category '{}' of plan type '{}'".format(
                            cat_key, spec.key
                        )
                    )
                for field_name, field_value in (cat_overrides or {}).items():
                    if field_name not in _CATEGORY_FIELDS:
                        raise ValueError(
                            "Variant overrides unknown BomCategory field '{}'".format(field_name)
                        )
                    setattr(category, field_name, field_value)
            continue
        if key not in _SPEC_FIELDS:
            raise ValueError("Variant overrides unknown PlanTypeSpec field '{}'".format(key))
        setattr(patched, key, value)
    return patched


@contextmanager
def apply(variant: Variant):
    """Apply a variant's overlay for the duration of the block, then restore it.

    Restoration happens in a `finally` and covers a partially-applied overlay,
    so a bad variant file leaves the process exactly as it found it.
    """
    saved_settings: Dict[str, object] = {}
    saved_prompts: Dict[str, object] = {}
    saved_specs: Dict[str, registry.PlanTypeSpec] = {}
    try:
        for key, value in (variant.settings or {}).items():
            if not hasattr(settings, key):
                raise ValueError(
                    "Variant '{}' sets unknown setting '{}'".format(variant.id, key)
                )
            saved_settings[key] = getattr(settings, key)
            setattr(settings, key, _coerce(saved_settings[key], value))

        for name, value in (variant.prompts or {}).items():
            if not hasattr(prompts_module, name):
                raise ValueError(
                    "Variant '{}' sets unknown prompt constant '{}'".format(variant.id, name)
                )
            saved_prompts[name] = getattr(prompts_module, name)
            setattr(prompts_module, name, value)

        for plan_type, overrides in (variant.spec_overrides or {}).items():
            original = registry.get(plan_type)
            if original is None:
                raise ValueError(
                    "Variant '{}' overrides unregistered plan type '{}'".format(
                        variant.id, plan_type
                    )
                )
            saved_specs[plan_type] = original
            registry.register(_overlay_spec(original, overrides))

        yield variant
    finally:
        for plan_type, original in saved_specs.items():
            registry.register(original)
        for name, value in saved_prompts.items():
            setattr(prompts_module, name, value)
        for key, value in saved_settings.items():
            setattr(settings, key, value)
