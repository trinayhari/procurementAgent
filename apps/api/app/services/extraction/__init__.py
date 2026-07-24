"""Document → Bill of Materials extraction via GPT-4.1 vision.

Public surface:
    extract_document(path, plan_type) -> ExtractionResult   # the orchestrator
    registry                                                # plan-type registry

Importing this package registers all built-in plan types (see `plan_types`).
"""
from app.services.extraction import plan_types as _plan_types  # noqa: F401 (registers specs)
from app.services.extraction import registry
from app.services.extraction.service import ExtractionResult, extract_document

__all__ = ["extract_document", "ExtractionResult", "registry"]
