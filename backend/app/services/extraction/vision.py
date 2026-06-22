"""GPT-4.1 vision client wrapper.

Isolates the OpenAI dependency behind one function, `extract`, that takes a plan
spec + page images and returns a validated `VisionExtraction`. Uses OpenAI
Structured Outputs (`response_format=VisionExtraction`) so the model is forced to
return our schema and we never parse free text.

The OpenAI SDK is imported lazily so the API still boots (and the mock path in
`service.py` still works) when the package or key is absent.
"""
from typing import List

from app.config import settings
from app.services.extraction.models import VisionExtraction
from app.services.extraction.prompts import (
    build_consolidation_system_prompt,
    build_consolidation_user_prompt,
    build_system_prompt,
    build_text_prompt,
    build_user_prompt,
)
from app.services.extraction.registry import PlanTypeSpec


class VisionUnavailable(Exception):
    """Raised when GPT-4.1 vision cannot be called (no key / SDK / API error)."""


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def _image_content(images_b64: List[str]) -> List[dict]:
    return [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": settings.vision_image_detail,
            },
        }
        for b64 in images_b64
    ]


def _client():
    if not settings.openai_api_key:
        raise VisionUnavailable("OPENAI_API_KEY is not set")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise VisionUnavailable("openai package is not installed") from exc
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)


def _parse(client, messages) -> VisionExtraction:
    try:
        completion = client.beta.chat.completions.parse(
            model=settings.openai_vision_model,
            messages=messages,
            response_format=VisionExtraction,
            temperature=0,
            max_tokens=settings.vision_max_tokens,
        )
    except Exception as exc:  # network / API / refusal
        raise VisionUnavailable(f"GPT-4.1 call failed: {exc}") from exc

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise VisionUnavailable("Model returned no parsable structured output")
    return parsed


def extract(spec: PlanTypeSpec, images_b64: List[str], sheet: str = None) -> VisionExtraction:
    """Extract a BOM from one or more page images. Pass `sheet` for a single-sheet pass."""
    messages = [
        {"role": "system", "content": build_system_prompt(spec)},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": build_user_prompt(spec, sheet=sheet)},
                *_image_content(images_b64),
            ],
        },
    ]
    return _parse(_client(), messages)


def extract_text(spec: PlanTypeSpec, sheets: List[dict]) -> VisionExtraction:
    """Text-only, one-shot extraction from the PDF's embedded text layer (no images).

    Far faster/cheaper than vision and more accurate for vector CAD plans, since the
    callouts, quantities, and schedules are already exact text.
    """
    messages = [
        {"role": "system", "content": build_system_prompt(spec)},
        {"role": "user", "content": build_text_prompt(spec, sheets)},
    ]
    return _parse(_client(), messages)


def consolidate(spec: PlanTypeSpec, per_sheet_items: List[dict]) -> VisionExtraction:
    """Text-only pass: merge sheet-by-sheet items into one deduplicated BOM."""
    messages = [
        {"role": "system", "content": build_consolidation_system_prompt()},
        {"role": "user", "content": build_consolidation_user_prompt(spec, per_sheet_items)},
    ]
    return _parse(_client(), messages)
