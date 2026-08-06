#!/usr/bin/env python3
"""Run a single event in an isolated process (used by web/streamlit GUIs)."""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Research one disaster event.")
    parser.add_argument("--disaster", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, default=None)
    parser.add_argument("--day", type=int, default=None)
    parser.add_argument("--output", required=True, help="Path to write JSON result.")
    args = parser.parse_args()

    logs: list[str] = []

    def capture_log(message: str) -> None:
        logs.append(message)
        print(message, file=sys.stderr, flush=True)

    try:
        from main import process_single_event

        result = process_single_event(
            disaster=args.disaster,
            country=args.country,
            location=args.location,
            year=args.year,
            month=args.month,
            day=args.day,
            log=capture_log,
        )
        payload = {
            "ok": True,
            "logs": logs,
            "search_query": result["search_query"],
            "event_id": result["event_id"],
            "changed_fields": result["changed_fields"],
            "sources": result["sources"],
            "record": result["record"],
        }
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "logs": logs}

    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
