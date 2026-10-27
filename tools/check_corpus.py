"""Read-only corpus validation. No game files are copied or modified."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import TypedDict

from cklang import ParseError, load, parse, render


class Arguments(argparse.Namespace):
    """Typed fields populated by argparse before corpus validation starts."""

    root: Path
    directories: list[str]
    limit: int
    fallback_encoding: str | None
    report: Path | None
    pretty: bool


class Failure(TypedDict):
    """One file that could not be decoded, parsed or round-tripped."""

    path: str
    error: str


class CorpusReport(TypedDict):
    """Stable JSON report schema, including explicitly decoded legacy files."""

    files: int
    characters: int
    fallback_files: list[str]
    failures: list[Failure]
    seconds: float
    successes: int


def main() -> int:
    """Validate files read-only; return zero on success, one on any failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--directories", nargs="+", default=["common", "events", "history"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fallback-encoding", help="Explicit fallback for files that are not UTF-8 (e.g. latin-1)")
    parser.add_argument("--report", type=Path, help="Write diagnostics outside the game directory")
    parser.add_argument("--pretty", action="store_true", help="Also check pretty token/comment fidelity and idempotence")
    args = parser.parse_args(namespace=Arguments())
    if not args.root.is_dir():
        parser.error("Corpus root does not exist")
    for directory in args.directories:
        if not (args.root / directory).is_dir() or not (args.root / directory).resolve().is_relative_to(args.root.resolve()):
            parser.error(f"Not a directory inside the corpus: {directory}")
    if args.report and args.report.resolve().is_relative_to(args.root.resolve()):
        parser.error("The report must be outside the read-only corpus")
    start = perf_counter()
    report: CorpusReport = {
        "files": 0, "characters": 0, "fallback_files": [], "failures": [],
        "seconds": 0.0, "successes": 0,
    }
    for directory in args.directories:
        for path in sorted((args.root / directory).rglob("*.txt")):
            if args.limit and report["files"] >= args.limit:
                break
            report["files"] += 1
            try:
                encoding = "utf-8"
                try:
                    tree = load(path)
                except UnicodeDecodeError:
                    if not args.fallback_encoding:
                        raise
                    encoding = args.fallback_encoding
                    tree = load(path, encoding=encoding)
                    report["fallback_files"].append(str(path.relative_to(args.root)))
                output = render(tree)
                raw = path.read_bytes()
                source = raw.decode(encoding)
                report["characters"] += len(source)
                if output != source or output.encode(encoding) != raw:
                    raise ValueError("Round-trip mismatch")
                if args.pretty:
                    formatted = render(tree, pretty=True)
                    rebuilt = parse(formatted, filename=str(path))
                    if [(t.kind, t.text) for t in rebuilt._tokens()] != [(t.kind, t.text) for t in tree._tokens()]:
                        raise ValueError("Pretty rendering changed significant tokens")
                    if [t.text for t in rebuilt._comments] != [t.text for t in tree._comments]:
                        raise ValueError("Pretty rendering changed comments")
                    if render(rebuilt, pretty=True) != formatted:
                        raise ValueError("Pretty rendering is not idempotent")
            except (ParseError, UnicodeError, ValueError, RecursionError) as error:
                failure: Failure = {"path": str(path.relative_to(args.root)), "error": str(error)}
                report["failures"].append(failure)
                print(json.dumps(failure, ensure_ascii=False), flush=True)
    report["seconds"] = round(perf_counter() - start, 3)
    report["successes"] = report["files"] - len(report["failures"])
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"failures", "fallback_files"}}, indent=2))
    print(f"Fallback encoding files: {len(report['fallback_files'])}")
    print(f"Failures: {len(report['failures'])}")
    return int(bool(report["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
