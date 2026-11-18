"""Monada Villa archive-to-story pipeline.

    python -m monada ingest   [--archive archive/]   # 1–4: scan, rate, dedupe, shot index, contact sheets
    python -m monada compose                          # 5: fill 24 reels + reveal, stories, carousels from the index
    python -m monada render   [--only R01 C1] [--langs zh ko] [--no-b]   # 6–7: MP4 / covers / SRT / QA
    python -m monada lint                             # compliance check of all copy (no media needed)
    python -m monada manifest                         # 30-day publication manifest
    python -m monada package                          # MONADA_CAMPAIGN/01…10 delivery folders
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import ROOT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="monada", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest")
    a.add_argument("--archive", type=Path, default=ROOT / "archive")
    sub.add_parser("compose")
    r = sub.add_parser("render")
    r.add_argument("--archive", type=Path, default=ROOT / "archive")
    r.add_argument("--only", nargs="*", help="substrings of spec names, e.g. R01 D05 C1")
    r.add_argument("--langs", nargs="*", default=[], help="extra burned-in subtitle versions: zh ko")
    r.add_argument("--no-b", action="store_true", help="skip alternate-hook B cuts")
    r.add_argument("--resume", action="store_true", help="skip outputs that already exist")
    r.add_argument("--skip-en", action="store_true", help="only the --langs versions (EN already rendered)")
    sub.add_parser("lint")
    sub.add_parser("manifest")
    sub.add_parser("package")
    pr = sub.add_parser("premium")
    pr.add_argument("--archive", type=Path, default=ROOT / "archive")
    pr.add_argument("--only", nargs="*")
    t = sub.add_parser("trend")
    t.add_argument("--archive", type=Path, default=ROOT / "archive")
    t.add_argument("--only", nargs="*")
    args = ap.parse_args(argv)

    if args.cmd == "ingest":
        from .ingest import ingest
        ingest(args.archive.resolve())
    elif args.cmd == "compose":
        from .compose import compose_all
        compose_all()
    elif args.cmd == "render":
        from .render import render_all
        render_all(args.archive.resolve(), args.only, args.langs, args.no_b, args.skip_en, args.resume)
    elif args.cmd == "lint":
        from .manifest import lint_all
        res = lint_all()
        return 1 if any(e for e, _ in res.values()) else 0
    elif args.cmd == "premium":
        from .premium import render_premium_all
        render_premium_all(args.archive.resolve(), args.only)
    elif args.cmd == "trend":
        from .trend import render_trends
        render_trends(args.archive.resolve(), args.only)
    elif args.cmd == "package":
        from .package import package
        package()
    elif args.cmd == "manifest":
        from .manifest import build_manifest
        build_manifest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
