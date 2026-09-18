#!/usr/bin/env python
"""Re-fetch the bench corpus PDFs from `bench-corpus/manifest.json`.

`bench-corpus/docs/` is gitignored — the manifest and the ground truth are what
travel in the repo, so a fresh checkout has the labels but none of the plan sets.
This script rebuilds `docs/` from the manifest's `source_url`s and verifies each
file against its recorded sha256, so a corpus that has silently drifted (a public
agency re-issuing a plan set at the same URL is common) is reported rather than
scored against stale ground truth.

Standard library only, on purpose: the bench must be re-fetchable without adding
a dependency to the API image.

    python scripts/fetch_corpus.py --dry-run     # say what would happen
    python scripts/fetch_corpus.py               # download what is missing
    python scripts/fetch_corpus.py --verify      # hash everything already present
    python scripts/fetch_corpus.py --stats       # re-derive pages/text-layer vs. manifest
    python scripts/fetch_corpus.py --only site-nps-crissy-field-01
    python scripts/fetch_corpus.py --force       # re-download even if present

Exit code is 1 when anything is missing, mismatched, or failed, so CI can gate on
it; 0 when the local corpus matches the manifest.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import ssl
import sys
from typing import Dict, List, Optional, Tuple

try:  # Python 3
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - Python 2 is not supported, fail loudly
    raise SystemExit("fetch_corpus.py requires Python 3")

# A plan set over this size is almost certainly a full multi-volume contract set;
# the bench does not need one and a 200 MB download is not a reasonable default.
MAX_BYTES = 150 * 1024 * 1024

# Several municipal document portals 403 an unknown client. This is the same
# request any browser would make for a public file; nothing is bypassed.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

TIMEOUT_SECONDS = 300


def corpus_dir() -> str:
    """`bench-corpus/` at the repo root, resolved from this file's location."""
    here = os.path.dirname(os.path.abspath(__file__))          # apps/api/scripts
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(repo_root, "bench-corpus")


def load_manifest(path: str) -> List[Dict]:
    with open(path) as fh:
        data = json.load(fh)
    docs = data.get("documents")
    if not isinstance(docs, list):
        raise SystemExit("%s has no 'documents' list" % path)
    return docs


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: str) -> Optional[str]:
    """Fetch `url` to `dest`. Returns an error string, or None on success.

    Written to a `.part` file and renamed only after the body is fully read, so an
    interrupted run never leaves a truncated PDF that would later hash-mismatch
    for a reason that looks like corpus drift.
    """
    # Some agency portals still serve an incomplete certificate chain. The corpus
    # is verified by sha256 against the manifest, which is the integrity check
    # that actually matters here, so a chain failure should not block a re-fetch.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        response = urlopen(request, timeout=TIMEOUT_SECONDS, context=context)
    except HTTPError as exc:
        return "HTTP %s" % exc.code
    except URLError as exc:
        return "unreachable: %s" % exc.reason
    except Exception as exc:  # noqa: BLE001 - report, never crash the whole run
        return "%s: %s" % (type(exc).__name__, exc)

    try:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_BYTES:
            return "too large (%s bytes > %d MB cap)" % (declared, MAX_BYTES // (1024 * 1024))
        body = response.read(MAX_BYTES + 1)
    finally:
        response.close()

    if len(body) > MAX_BYTES:
        return "too large (> %d MB cap)" % (MAX_BYTES // (1024 * 1024))
    if not body.startswith(b"%PDF"):
        # Usually an interstitial HTML page: a login wall, a cookie gate, or a
        # "this document has moved" notice. Saving it would poison the corpus.
        return "not a PDF (server returned %d bytes starting %r)" % (len(body), body[:12])

    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    partial = dest + ".part"
    with open(partial, "wb") as fh:
        fh.write(body)
    os.rename(partial, dest)
    return None


def probe(path: str) -> Dict:
    """Re-derive the manifest's file facts from the PDF itself.

    `pages` and `has_text_layer` are read the same way `extraction.pdf` reads them
    (PyMuPDF, 500-character text threshold) so the manifest describes what the
    extraction pipeline will actually see. PyMuPDF is imported here rather than at
    module level to keep the download path standard-library-only.
    """
    import fitz  # PyMuPDF

    with open(path, "rb") as fh:
        blob = fh.read()
    facts = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
    with fitz.open(path) as doc:
        facts["pages"] = doc.page_count
        chars = 0
        for page in doc:
            chars += len(page.get_text().strip())
            if chars >= 500:
                break
        facts["has_text_layer"] = chars >= 500
    return facts


def stats_entry(doc: Dict, root: str) -> Tuple[str, str]:
    """Compare one manifest entry's recorded file facts against the actual PDF."""
    doc_id = doc.get("id", "<no id>")
    rel = doc.get("file") or os.path.join("docs", "%s.pdf" % doc_id)
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return "missing", "not present locally"
    try:
        facts = probe(path)
    except ImportError:
        raise SystemExit("--stats needs PyMuPDF: apps/api/.venv/bin/python -m pip install pymupdf")
    except Exception as exc:  # noqa: BLE001 - a corrupt PDF is a corpus problem, not a crash
        return "failed", "cannot read: %s: %s" % (type(exc).__name__, exc)

    diffs = ["%s: manifest %r, actual %r" % (k, doc.get(k), v)
             for k, v in sorted(facts.items()) if doc.get(k) != v]
    summary = "%d pages, %s, %.1f MB, text_layer=%s" % (
        facts["pages"], facts["sha256"][:12], facts["bytes"] / 1e6, facts["has_text_layer"])
    if diffs:
        return "mismatch", summary + "\n      " + "\n      ".join(diffs)
    return "ok", summary + " — matches manifest"


def check_entry(doc: Dict, root: str, args) -> Tuple[str, str]:
    """Process one manifest entry. Returns (status, human-readable detail).

    Status is one of: ok, downloaded, missing, mismatch, no-url, failed, skipped,
    would-download, would-verify.
    """
    doc_id = doc.get("id", "<no id>")
    rel = doc.get("file") or os.path.join("docs", "%s.pdf" % doc_id)
    path = os.path.join(root, rel)
    url = doc.get("source_url")
    expected = doc.get("sha256")
    present = os.path.isfile(path)

    if present and not args.force:
        if not (args.verify or args.force):
            return "ok", "present (%s bytes, not hashed — use --verify)" % os.path.getsize(path)
        if not expected:
            return "ok", "present, manifest records no sha256"
        actual = sha256_of(path)
        if actual == expected:
            return "ok", "present, sha256 matches"
        return "mismatch", "sha256 differs\n      expected %s\n      actual   %s" % (expected, actual)

    if not url:
        return "no-url", "not present locally and the manifest has no source_url"

    if args.dry_run:
        return "would-download", "would fetch %s" % url

    error = download(url, path)
    if error:
        return "failed", "%s (%s)" % (error, url)

    if expected:
        actual = sha256_of(path)
        if actual != expected:
            return (
                "mismatch",
                "downloaded but sha256 differs — the source may have re-issued the "
                "document\n      expected %s\n      actual   %s" % (expected, actual),
            )
    return "downloaded", "fetched %s bytes" % os.path.getsize(path)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be fetched without downloading anything",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="hash files that are already present and compare against the manifest",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="re-derive sha256/bytes/pages/has_text_layer from the PDFs and diff "
             "them against the manifest (needs PyMuPDF; downloads nothing)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download every entry that has a source_url, even if present",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="DOC_ID",
        help="restrict to this document id (repeatable)",
    )
    parser.add_argument(
        "--corpus-dir",
        default=None,
        help="override the bench-corpus directory (default: repo root/bench-corpus)",
    )
    args = parser.parse_args(argv)

    root = args.corpus_dir or corpus_dir()
    manifest_path = os.path.join(root, "manifest.json")
    if not os.path.isfile(manifest_path):
        print("no manifest at %s" % manifest_path, file=sys.stderr)
        return 1

    documents = load_manifest(manifest_path)
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {d.get("id") for d in documents}
        if unknown:
            print("unknown document id(s): %s" % ", ".join(sorted(unknown)), file=sys.stderr)
            return 1
        documents = [d for d in documents if d.get("id") in wanted]

    print("corpus: %s" % root)
    print("%d document(s)%s\n" % (len(documents), " [dry run]" if args.dry_run else ""))

    tally = {}
    for doc in documents:
        status, detail = stats_entry(doc, root) if args.stats else check_entry(doc, root, args)
        tally[status] = tally.get(status, 0) + 1
        marker = {
            "ok": "  ok  ",
            "downloaded": " new  ",
            "would-download": " plan ",
            "mismatch": " DRIFT",
            "missing": " MISS ",
            "no-url": " NOURL",
            "failed": " FAIL ",
        }.get(status, " ---- ")
        print("[%s] %s" % (marker, doc.get("id", "<no id>")))
        print("      %s" % detail)

    print("\nsummary: " + ", ".join("%s=%d" % (k, tally[k]) for k in sorted(tally)))

    # A dry run is a report, not a gate — it should not fail just because files
    # are legitimately absent, which is the normal state on a fresh checkout.
    if args.dry_run:
        return 0
    bad = sum(tally.get(k, 0) for k in ("mismatch", "missing", "no-url", "failed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
