# Eval bench — shared responsibilities

Branch `feat/extraction-eval-bench`, worktree
`/Users/trinayhari/procurementAgent/.claude/worktrees/eval-bench`.

The contract every track builds against is [eval-harness.md](eval-harness.md).
It is frozen: if a track needs a different shape, it changes that document and
says so, because the other tracks are being built against it concurrently.

## File ownership

Tracks run in the same worktree at the same time. **Only touch the paths you
own.** Anything shared is already in place (below) — if you think you need to
edit a file another track owns, say so instead of editing it.

| Track | Owns | Must not touch |
|---|---|---|
| **A — Eval core** | `apps/api/app/eval/**`, `apps/api/tests/test_eval_*.py` | routes, schemas, `apps/bench/`, `bench-corpus/` |
| **B — Bench API** | `apps/api/app/api/routes/bench.py`, `apps/api/app/schemas/bench.py`, `apps/api/tests/test_bench_api.py` | `apps/api/app/eval/**` (consume it, don't edit) |
| **C — Bench app** | `apps/bench/**`, root `package-lock.json` | everything under `apps/api/` |
| **D — Corpus** | `bench-corpus/**`, `apps/api/scripts/fetch_corpus.py` | `apps/api/app/**`, `apps/bench/**` |

Already wired, by the coordinator — do not redo or re-edit:

- `apps/api/app/config.py` — `bench_enabled`, `bench_corpus_dir`, `bench_db_url`, CORS for :5185
- `apps/api/app/main.py` — bench router mounted, production-gated
- `apps/api/app/api/routes/bench.py` — stub router with `/bench/status` (B fills it in)
- root `package.json` — `dev:bench` script
- `.gitignore` — `bench-corpus/docs/`
- `.claude/launch.json` — `bench-api` (:8040), `bench-web` (:5185)

## Sequencing

A, C, and D run in parallel. **B starts after A lands**, because it is a thin
adapter over A's module surface and building it against a module that does not
exist yet just invents an integration bug.

C builds against the frozen HTTP contract with a dev-only mock adapter, so it is
not blocked on B.

## Rules that apply to every track

- **Python 3.8.** `requires-python = ">=3.8"`; the local venv is 3.8.3. Use
  `typing.Optional` / `List` / `Dict`, never `X | None` or `list[X]` in
  annotations. Verify with `apps/api/.venv/bin/python`, never system `python3`.
- **No placeholder data.** Empty states say what is missing and how to fix it.
  Never invent a corpus document, a metric, or a score.
- **An undefined metric is `None`/`—`, not `0.0`.** They mean different things.
- **Never present a mocked extraction as an accuracy result.** No OpenAI key →
  the pipeline returns `mocked=True`; that must be flagged everywhere it surfaces.
- **Cost discipline.** Every run makes real model calls against real plan sets.
  Trials default to 1. Nothing auto-runs. No "run everything" default.
- Do not `git commit`, `git push`, or open a PR. Leave changes in the worktree.
- Match the surrounding code's style: module docstrings that explain *why*,
  comments only where the reason isn't obvious from the code.

## Definition of done, per track

- **A** — `python -m app.eval validate|corpus|variants` run clean; scoring has
  unit tests covering the matcher's hard cases (size-token gate, alias hit,
  partial-completeness precision, forbidden hit, unit normalisation); `pytest`
  green.
- **B** — every endpoint in the contract implemented, OpenAPI regenerates, tests
  cover the production gate and the run lifecycle.
- **C** — `npm run build --workspace @proq/bench` and `typecheck` pass; all four
  panels work; verified in the browser against the mock adapter at minimum.
- **D** — `bench-corpus/manifest.json` validates, every entry has provenance and
  a license, ground truth authored for a starter set, `fetch_corpus.py`
  re-fetches from the manifest reproducibly.
