from __future__ import annotations

import argparse
import json
from typing import Any

from pydantic import BaseModel

from document_evidence_mcp.models import BBox
from document_evidence_mcp.service import DocumentEvidenceService


def _emit(value: Any) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="document-evidence",
        description="Manage the local document evidence index.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest", help="Import a document.")
    ingest.add_argument("path")
    ingest.add_argument("--language", action="append", dest="languages")
    ingest.add_argument("--ocr-mode", choices=("auto", "never", "always"), default="auto")
    ingest.add_argument("--force", action="store_true")

    search = subcommands.add_parser("search", help="Search indexed evidence.")
    search.add_argument("query")
    search.add_argument("--document-id")
    search.add_argument("--limit", type=int, default=4)
    search.add_argument("--max-chars", type=int, default=6_000)

    evidence = subcommands.add_parser("evidence", help="Read evidence by stable ID.")
    evidence.add_argument("evidence_ids", nargs="+")
    evidence.add_argument("--max-chars", type=int, default=8_000)

    listing = subcommands.add_parser("list", help="List indexed documents.")
    listing.add_argument("--limit", type=int, default=20)

    inspect = subcommands.add_parser("show", help="Show one document summary.")
    inspect.add_argument("document_id")

    crop = subcommands.add_parser("crop", help="Render one PDF rectangle.")
    crop.add_argument("document_id")
    crop.add_argument("page", type=int)
    crop.add_argument("x0", type=float)
    crop.add_argument("y0", type=float)
    crop.add_argument("x1", type=float)
    crop.add_argument("y1", type=float)
    crop.add_argument("--dpi", type=int, default=144)

    subcommands.add_parser("doctor", help="Check local capabilities.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    service = DocumentEvidenceService()
    if args.command == "ingest":
        result = service.ingest_document(
            args.path,
            languages=args.languages,
            ocr_mode=args.ocr_mode,
            force=args.force,
        )
    elif args.command == "search":
        result = service.search_evidence(
            args.query,
            document_id=args.document_id,
            limit=args.limit,
            max_chars=args.max_chars,
        )
    elif args.command == "evidence":
        result = service.get_evidence(args.evidence_ids, max_chars=args.max_chars)
    elif args.command == "list":
        result = service.list_documents(limit=args.limit)
    elif args.command == "show":
        result = service.get_document(args.document_id)
    elif args.command == "crop":
        result = service.render_crop(
            args.document_id,
            page=args.page,
            bbox=BBox(x0=args.x0, y0=args.y0, x1=args.x1, y1=args.y1),
            dpi=args.dpi,
        )
    elif args.command == "doctor":
        result = service.doctor()
    else:
        raise AssertionError(f"unhandled command: {args.command}")
    _emit(result)


if __name__ == "__main__":
    main()
