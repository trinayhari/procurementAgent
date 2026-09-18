"""Variant overlays — and, above all, that they are fully undone.

`apply()` mutates process-global state (the shared `settings` object, the
prompts module, the plan-type registry). A leak here would silently poison every
later extraction in the process, so restoration is tested on the happy path, on
an exception inside the block, and on a variant that fails halfway through being
applied.
"""
import json

import pytest

from app.config import settings
from app.eval import variants
from app.eval.variants import Variant
from app.services.extraction import prompts as prompts_module
from app.services.extraction import registry


@pytest.fixture()
def variants_root(tmp_path, monkeypatch):
    root = tmp_path / "bench-corpus"
    (root / "variants").mkdir(parents=True)
    monkeypatch.setattr(settings, "bench_corpus_dir", str(root))
    return root


def snapshot():
    """Everything apply() is allowed to touch, as comparable values."""
    spec = registry.require("site_plan")
    return {
        "text_pass_min_items": settings.text_pass_min_items,
        "vision_tile_cols": settings.vision_tile_cols,
        "prefer_vision": spec.prefer_vision,
        "SYSTEM_PROMPT": prompts_module.SYSTEM_PROMPT,
        "guidance": spec.prompt_guidance,
        "water_description": spec.category("water").description,
        "spec_object": id(registry.require("site_plan")),
    }


VARIANT = Variant(
    id="text-first-strict",
    label="Text-first, stricter escalation",
    description="Raise the text-pass floor.",
    settings={"text_pass_min_items": 8, "vision_tile_cols": 4},
    prompts={"SYSTEM_PROMPT": "OVERRIDDEN SYSTEM PROMPT"},
    spec_overrides={
        "site_plan": {
            "prompt_guidance": "OVERRIDDEN GUIDANCE",
            "prefer_vision": True,
            "categories": {"water": {"description": "OVERRIDDEN WATER", "examples": ["x"]}},
        }
    },
)


# ------------------------------------------------------------------ apply
def test_apply_patches_all_three_layers_and_restores_them():
    before = snapshot()
    with variants.apply(VARIANT):
        spec = registry.require("site_plan")
        assert settings.text_pass_min_items == 8
        assert settings.vision_tile_cols == 4
        assert prompts_module.SYSTEM_PROMPT == "OVERRIDDEN SYSTEM PROMPT"
        assert spec.prefer_vision is True
        assert spec.prompt_guidance == "OVERRIDDEN GUIDANCE"
        assert spec.category("water").description == "OVERRIDDEN WATER"
        # The prompt builder must actually see the overlay.
        assert "OVERRIDDEN SYSTEM PROMPT" in prompts_module.build_system_prompt(spec)
        assert "OVERRIDDEN WATER" in prompts_module.build_system_prompt(spec)
    assert snapshot() == before


def test_restoration_survives_an_exception_in_the_body():
    before = snapshot()
    with pytest.raises(RuntimeError):
        with variants.apply(VARIANT):
            assert settings.text_pass_min_items == 8
            raise RuntimeError("extraction blew up")
    assert snapshot() == before


def test_a_partially_applied_variant_is_rolled_back():
    """The settings patch lands, then the prompt name is bogus — nothing may stick."""
    before = snapshot()
    broken = Variant(
        id="broken",
        label="broken",
        settings={"text_pass_min_items": 99},
        prompts={"NO_SUCH_PROMPT": "x"},
    )
    with pytest.raises(ValueError):
        with variants.apply(broken):
            pass  # pragma: no cover - apply() raises before the body runs
    assert snapshot() == before


def test_unknown_setting_and_unknown_plan_type_fail_loudly():
    for bad in (
        Variant(id="a", label="a", settings={"not_a_setting": 1}),
        Variant(id="b", label="b", spec_overrides={"no_such_plan": {"prefer_vision": True}}),
        Variant(id="c", label="c", spec_overrides={"site_plan": {"no_such_field": 1}}),
        Variant(id="d", label="d", spec_overrides={"site_plan": {"categories": {"nope": {}}}}),
    ):
        before = snapshot()
        with pytest.raises(ValueError):
            with variants.apply(bad):
                pass  # pragma: no cover
        assert snapshot() == before


def test_the_original_spec_object_is_never_mutated():
    original = registry.require("site_plan")
    original_guidance = original.prompt_guidance
    with variants.apply(VARIANT):
        assert registry.require("site_plan") is not original
    assert registry.require("site_plan") is original
    assert original.prompt_guidance == original_guidance


def test_json_string_settings_are_coerced_to_the_setting_type():
    with variants.apply(Variant(id="s", label="s", settings={"text_pass_min_items": "8"})):
        assert settings.text_pass_min_items == 8
    with variants.apply(Variant(id="b", label="b", settings={"seed_demo_data": "false"})):
        assert settings.seed_demo_data is False


# ------------------------------------------------------------- loading
def test_baseline_is_synthesised_when_no_file_defines_it(variants_root):
    loaded = variants.load_variants()
    assert [v.id for v in loaded] == ["baseline"]
    assert loaded[0].settings == {} and loaded[0].prompts == {}
    with variants.apply(variants.get_variant("baseline")):
        pass  # the empty overlay is a no-op by construction


def test_variants_load_from_disk_with_baseline_first(variants_root):
    (variants_root / "variants" / "zz.json").write_text(
        json.dumps({"id": "zz-strict", "label": "Strict", "settings": {"text_pass_min_items": 8}}),
        encoding="utf-8",
    )
    (variants_root / "variants" / "broken.json").write_text("{oops", encoding="utf-8")
    loaded = variants.load_variants()
    assert [v.id for v in loaded] == ["baseline", "zz-strict"]  # broken file is skipped
    assert variants.get_variant("zz-strict").settings == {"text_pass_min_items": 8}
    with pytest.raises(KeyError):
        variants.get_variant("nope")


def test_validate_variant_reports_problems_without_applying():
    before = snapshot()
    problems = variants.validate_variant(
        Variant(
            id="x",
            label="x",
            settings={"nope": 1},
            prompts={"ALSO_NOPE": "x"},
            spec_overrides={"site_plan": {"categories": {"ghost": {}}}, "ghost_plan": {}},
        )
    )
    assert len(problems) == 4
    assert snapshot() == before
    assert variants.validate_variant(VARIANT) == []
