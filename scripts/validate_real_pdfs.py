from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from document_evidence_mcp.service import DocumentEvidenceService


def _language_and_query(name: str) -> tuple[list[str], str]:
    cases = (
        ("DIN17440", ["de"], "Werkstoff"),
        ("TL 4800", ["de"], "Sinterstahl"),
        ("Accuracy and precision", ["en"], "rolling resistance"),
        ("CONTRIBUTION TO ACCURATE", ["en"], "aerodynamic"),
        ("CAEPI", ["zh"], "催化转化器"),
        ("排气污染物", ["zh"], "排气污染物"),
        ("GB_T 17692", ["zh"], "净功率"),
        ("GB_T 6379", ["zh"], "精密度"),
        ("联电氧存储", ["zh", "en"], "Oxygen Storage"),
    )
    for marker, languages, query in cases:
        if marker in name:
            return languages, query
    return ["zh", "en", "de"], Path(name).stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    service = DocumentEvidenceService()
    records: list[dict[str, Any]] = []
    started = time.perf_counter()
    for path in sorted(args.pdf_dir.resolve().glob("*.pdf")):
        languages, query = _language_and_query(path.name)
        item_started = time.perf_counter()
        ingested = service.ingest_document(
            path,
            languages=languages,
            ocr_mode="auto",
        )
        search = service.search_evidence(
            query,
            document_id=ingested.document_id,
            limit=3,
            max_chars=2_000,
        )
        record = {
            "name": path.name,
            "languages": languages,
            "query": query,
            "elapsed_seconds": round(time.perf_counter() - item_started, 3),
            **ingested.model_dump(mode="json"),
            "search_hit_count": len(search.hits),
            "top_hit": (
                {
                    "evidence_id": search.hits[0].evidence_id,
                    "text": search.hits[0].text[:240],
                    "kind": search.hits[0].kind,
                    "page": search.hits[0].page,
                    "bbox": (
                        search.hits[0].bbox.model_dump(mode="json") if search.hits[0].bbox else None
                    ),
                    "confidence": search.hits[0].confidence,
                    "coordinate_space": search.hits[0].metadata.get("coordinate_space"),
                }
                if search.hits
                else None
            ),
        }
        records.append(record)
        print("PDF_RESULT=" + json.dumps(record, ensure_ascii=False), flush=True)

    result = {
        "pdf_dir": str(args.pdf_dir.resolve()),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "document_count": len(records),
        "documents": records,
    }
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("VALIDATION_SUMMARY=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
