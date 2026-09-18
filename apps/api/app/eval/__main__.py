"""CLI for the eval bench — `python -m app.eval …`.

Human-readable by default, `--json` everywhere for machine use. The corpus may
not exist on a given machine (the PDFs are gitignored and the manifest is owned
by another track), so every read-only subcommand degrades to a clear message
instead of a traceback.

Cost discipline: `run` requires an explicit `--docs`. There is deliberately no
"run everything" default — a run makes real model calls against real plan sets.
"""
import argparse
import json
import sys
from typing import List, Optional

from app.eval import corpus, runner, scoring, store, variants

DASH = u"—"  # an undefined metric is never printed as 0.00


def _fmt(value, places: int = 3) -> str:
    if value is None:
        return DASH
    if isinstance(value, float):
        return "{:.{}f}".format(value, places)
    return str(value)


def _emit(args, payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


# ------------------------------------------------------------------ corpus
def cmd_corpus(args) -> int:
    try:
        docs = corpus.load_corpus()
    except corpus.CorpusError as exc:
        if args.json:
            _emit(args, {"documents": [], "problem": str(exc)})
        else:
            print(str(exc))
            print("Nothing to list yet.")
        return 0

    if args.json:
        _emit(args, {"corpus_dir": corpus.corpus_dir(), "documents": [vars(d) for d in docs]})
        return 0

    print("corpus: {}".format(corpus.corpus_dir()))
    if not docs:
        print("  (manifest has no documents yet)")
        return 0
    print("  {:<28} {:<16} {:<7} {:<7} {}".format("ID", "PLAN TYPE", "PDF", "TRUTH", "TITLE"))
    for doc in docs:
        print(
            "  {:<28} {:<16} {:<7} {:<7} {}".format(
                doc.id[:28],
                doc.plan_type[:16],
                "yes" if doc.exists else "MISSING",
                "yes" if doc.has_truth else "-",
                doc.title[:50],
            )
        )
    labelled = sum(1 for d in docs if d.has_truth)
    present = sum(1 for d in docs if d.exists)
    print(
        "\n  {} document(s) · {} labelled · {} PDF(s) present locally".format(
            len(docs), labelled, present
        )
    )
    return 0


def cmd_validate(args) -> int:
    problems = corpus.validate_corpus()
    populated = corpus.corpus_exists()
    variant_problems = []
    for variant in variants.load_variants():
        for problem in variants.validate_variant(variant):
            variant_problems.append("variant '{}': {}".format(variant.id, problem))

    if args.json:
        _emit(args, {"populated": populated, "problems": problems + variant_problems})
    else:
        if not populated:
            print(problems[0] if problems else "corpus not populated")
            print("Nothing to validate yet.")
        elif problems or variant_problems:
            for problem in problems + variant_problems:
                print("  ✗ {}".format(problem))
            print("\n{} problem(s)".format(len(problems) + len(variant_problems)))
        else:
            print("corpus is valid ({})".format(corpus.corpus_dir()))
    # An unpopulated corpus is "not built yet", not a validation failure.
    if not populated:
        return 0
    return 1 if (problems or variant_problems) else 0


def cmd_variants(args) -> int:
    all_variants = variants.load_variants()
    if args.json:
        _emit(
            args,
            [
                dict(v.to_dict(), problems=variants.validate_variant(v))
                for v in all_variants
            ],
        )
        return 0
    print("variants: {}".format(variants.variants_dir()))
    for variant in all_variants:
        overlays = []
        if variant.settings:
            overlays.append("{} setting(s)".format(len(variant.settings)))
        if variant.prompts:
            overlays.append("{} prompt(s)".format(len(variant.prompts)))
        if variant.spec_overrides:
            overlays.append("{} spec(s)".format(len(variant.spec_overrides)))
        print(
            "  {:<24} {:<34} {}".format(
                variant.id[:24], variant.label[:34], ", ".join(overlays) or "no overrides"
            )
        )
        for problem in variants.validate_variant(variant):
            print("      ✗ {}".format(problem))
    if len(all_variants) == 1:
        print("\n  only the synthesised baseline — add files under {}".format(variants.variants_dir()))
    return 0


# --------------------------------------------------------------------- runs
def _split(value: Optional[str]) -> List[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def cmd_run(args) -> int:
    doc_ids = _split(args.docs)
    if not doc_ids:
        print("--docs is required: name the documents to run (there is no 'run everything').")
        return 2
    variant_ids = _split(args.variant) or [variants.BASELINE_ID]

    try:
        known = {d.id for d in corpus.load_corpus()}
    except corpus.CorpusError as exc:
        print(str(exc))
        return 2
    unknown = [d for d in doc_ids if d not in known]
    if unknown:
        print("unknown document(s): {}".format(", ".join(unknown)))
        return 2
    for vid in variant_ids:
        try:
            variants.get_variant(vid)
        except KeyError as exc:
            print(str(exc))
            return 2

    extractions = len(doc_ids) * len(variant_ids) * args.trials
    print(
        "{} extraction(s): {} doc(s) × {} variant(s) × {} trial(s)".format(
            extractions, len(doc_ids), len(variant_ids), args.trials
        )
    )
    run_ids = store.create_run(
        variant_ids=variant_ids,
        doc_ids=doc_ids,
        plan_type=args.plan_type,
        trials=args.trials,
        notes=args.notes,
    )
    results = []
    for run_id, variant_id in zip(run_ids, variant_ids):
        print("\nrun {} · variant {}".format(run_id, variant_id))

        def progress(done, total, _rid=run_id):
            print("  {}/{}".format(done, total))

        results.append(runner.execute_run(run_id, on_progress=None if args.json else progress))

    if args.json:
        _emit(args, results)
        return 0
    for run in results:
        _print_run(run, detail=True)
    return 0


def cmd_runs(args) -> int:
    runs = store.list_runs(limit=args.limit)
    if args.json:
        _emit(args, runs)
        return 0
    if not runs:
        print("no runs yet — `python -m app.eval run --docs <id> --variant baseline`")
        return 0
    print(
        "  {:<34} {:<10} {:<18} {:<7} {:<7} {:<7} {}".format(
            "RUN", "STATUS", "VARIANT", "P", "R", "F1", "WHEN"
        )
    )
    for run in runs:
        metrics = (run.get("summary") or {}).get("metrics") or {}
        mocked = (run.get("summary") or {}).get("mocked")
        print(
            "  {:<34} {:<10} {:<18} {:<7} {:<7} {:<7} {}{}".format(
                run["id"],
                run["status"],
                (run["variant_id"] or "")[:18],
                _fmt(metrics.get("precision"), 2),
                _fmt(metrics.get("recall"), 2),
                _fmt(metrics.get("f1"), 2),
                run["created_at"],
                "  [MOCKED]" if mocked else "",
            )
        )
    return 0


def cmd_show(args) -> int:
    run = store.get_run(args.run_id)
    if run is None:
        print("no such run: {}".format(args.run_id))
        return 2
    if args.json:
        _emit(args, run)
        return 0
    _print_run(run, detail=True)
    return 0


def cmd_rescore(args) -> int:
    """Re-score stored trials with the current scorer + truth — no model calls."""
    from app.eval import runner

    for run_id in args.run_ids:
        try:
            summary = runner.rescore_run(run_id)
        except KeyError as exc:
            print(str(exc))
            return 2
        if args.json:
            _emit(args, {"run_id": run_id, "summary": summary})
            continue
        _print_run(store.get_run(run_id), detail=args.detail)
    return 0


def cmd_compare(args) -> int:
    a = store.get_run(args.a)
    b = store.get_run(args.b)
    missing = [rid for rid, run in ((args.a, a), (args.b, b)) if run is None]
    if missing:
        print("no such run(s): {}".format(", ".join(missing)))
        return 2
    deltas = compare_runs(a, b)
    if args.json:
        _emit(args, {"a": a, "b": b, "deltas": deltas})
        return 0
    print("A {} · {}".format(a["id"], a["variant_id"]))
    print("B {} · {}".format(b["id"], b["variant_id"]))
    if (a.get("summary") or {}).get("mocked") or (b.get("summary") or {}).get("mocked"):
        print("\n  MOCKED results are involved — these are not accuracy numbers.")
    print("\n  {:<20} {:>8} {:>8} {:>9}".format("METRIC", "A", "B", "DELTA"))
    for key in scoring.METRIC_KEYS:
        d = deltas[key]
        print(
            "  {:<20} {:>8} {:>8} {:>9}".format(
                key, _fmt(d["a"], 3), _fmt(d["b"], 3),
                DASH if d["delta"] is None else "{:+.3f}".format(d["delta"]),
            )
        )
    return 0


def compare_runs(a: dict, b: dict) -> dict:
    """Per-metric A/B deltas. A delta is None unless BOTH sides defined the metric."""
    ma = ((a.get("summary") or {}).get("metrics") or {})
    mb = ((b.get("summary") or {}).get("metrics") or {})
    out = {}
    for key in scoring.METRIC_KEYS:
        va, vb = ma.get(key), mb.get(key)
        out[key] = {
            "a": va,
            "b": vb,
            "delta": (vb - va) if (va is not None and vb is not None) else None,
        }
    return out


def _print_run(run: dict, detail: bool = False) -> None:
    summary = run.get("summary") or {}
    metrics = summary.get("metrics") or {}
    print(
        "\nrun {} · {} · variant {} · {}/{}".format(
            run["id"], run["status"], run["variant_id"],
            run.get("progress_done"), run.get("progress_total"),
        )
    )
    if run.get("error"):
        print("  error: {}".format(run["error"]))
    if summary.get("mocked"):
        print("  MOCKED — no OpenAI key; these are not accuracy results.")
    if not metrics:
        print("  metrics: {}".format(summary.get("note") or "none"))
    else:
        print(
            "  precision {}  recall {}  f1 {}  qty {}  unit {}  category {}  usable {}  hallucinations {}  scale-errors {}".format(
                _fmt(metrics.get("precision")), _fmt(metrics.get("recall")),
                _fmt(metrics.get("f1")), _fmt(metrics.get("quantity_accuracy")),
                _fmt(metrics.get("unit_accuracy")), _fmt(metrics.get("category_accuracy")),
                _fmt(metrics.get("usable_recall")),
                metrics.get("hallucinations", 0),
                (metrics.get("counts") or {}).get("scale_errors", 0),
            )
        )
    if not detail:
        return
    for trial in run.get("trials_detail") or []:
        flag = " [MOCKED]" if trial.get("mocked") else ""
        print("\n  {} (trial {}){} · {}".format(
            trial["doc_id"], trial["trial_index"], flag, trial["status"]
        ))
        if trial.get("error"):
            print("    error: {}".format(trial["error"]))
        score = trial.get("score")
        if not score:
            continue
        print(
            "    precision {}  recall {}  f1 {}".format(
                _fmt(score.get("precision")), _fmt(score.get("recall")), _fmt(score.get("f1"))
            )
        )
        for kind, label in (("miss", "missing"), ("extra", "extra"), ("forbidden", "HALLUCINATED")):
            names = [
                m.get("truth_name") or m.get("extracted_name")
                for m in score.get("matches") or []
                if m.get("kind") == kind
            ]
            if names:
                print("    {}: {}".format(label, ", ".join(n for n in names if n)))
        wrong_qty = [
            m for m in score.get("matches") or []
            if m.get("kind") == "hit" and m.get("quantity_ok") is False
        ]
        for m in wrong_qty:
            print(
                "    wrong quantity: {} — got {}, want {}".format(
                    m.get("truth_name"), _fmt(m.get("quantity_got"), 2), _fmt(m.get("quantity_want"), 2)
                )
            )


# ---------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.eval", description="Proq extraction eval bench")
    subs = parser.add_subparsers(dest="command")

    def add(name, func, help_text):
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("--json", action="store_true", help="machine-readable output")
        sub.set_defaults(func=func)
        return sub

    add("corpus", cmd_corpus, "list corpus documents + truth coverage")
    add("validate", cmd_validate, "validate the manifest, truth files, and variants")
    add("variants", cmd_variants, "list tuning variants")

    run = add("run", cmd_run, "run an evaluation (makes real model calls)")
    run.add_argument("--docs", help="comma-separated corpus document ids (required)")
    run.add_argument("--variant", default=variants.BASELINE_ID, help="comma-separated variant ids")
    run.add_argument("--trials", type=int, default=1, help="trials per document (default 1)")
    run.add_argument("--plan-type", default=None, help="override each document's plan type")
    run.add_argument("--notes", default=None, help="batch label shared by the created runs")

    runs = add("runs", cmd_runs, "recent runs + headline metrics")
    runs.add_argument("--limit", type=int, default=20)

    show = add("show", cmd_show, "per-document detail for one run")
    show.add_argument("run_id")

    rescore = add("rescore", cmd_rescore, "re-score stored runs with the current scorer/truth (no model calls)")
    rescore.add_argument("run_ids", nargs="+")
    rescore.add_argument("--detail", action="store_true", help="print per-document detail")

    compare = add("compare", cmd_compare, "metric deltas between two runs")
    compare.add_argument("a")
    compare.add_argument("b")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
