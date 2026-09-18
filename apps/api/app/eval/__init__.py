"""Eval core for the extraction accuracy bench (see docs/eval-harness.md).

Pure Python — NO FastAPI imports anywhere under this package. The CLI
(`python -m app.eval`), pytest, and the dev-only bench API all sit on top of
this same surface, so it must import cleanly with nothing but the app's own
config and the extraction registry available.

Layout:
  corpus.py    load/validate the labelled corpus (manifest + ground truth)
  scoring.py   match an extraction against ground truth → metrics
  variants.py  config/prompt/spec overlays, applied as a context manager
  runner.py    execute a run (docs × trials) for one variant
  store.py     SQLite persistence of runs/trials, in its OWN database
  __main__.py  the CLI
"""
from app.eval import corpus, runner, scoring, store, variants  # noqa: F401

__all__ = ["corpus", "runner", "scoring", "store", "variants"]
