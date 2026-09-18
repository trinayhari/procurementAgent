"""The production extraction prompts carry the rules the eval bench proved out.

No model call: these pin that a promoted rule is present in what the model is
actually sent (`build_system_prompt` for both the text and vision paths) so a
prompt edit cannot silently drop it, and that it appears exactly once.
"""
from app.services.extraction import prompts, registry


def test_system_prompt_lists_only_new_work():
    """Promoted from the `new-work-only` bench variant (2026-09-17): existing
    equipment on retrofit/addition sets was 5 of 5 baseline hallucinations."""
    for spec in registry.all_specs():
        text = prompts.build_system_prompt(spec)
        assert text.count("EXISTING vs NEW:") == 1, spec.key
        assert "BY UTILITY" in text and "Demolition and removal are not materials" in text
    assert prompts.build_system_prompt(None).count("EXISTING vs NEW:") == 1


def test_repeated_units_rule_still_present():
    text = prompts.build_system_prompt(registry.require("electrical_plan"))
    assert "REPEATED UNITS:" in text
    # Order: the general estimator rules come first, plan-type guidance after.
    assert text.index("EXISTING vs NEW:") < text.index("Category definitions")
