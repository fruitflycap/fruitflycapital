"""Command-line validation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import OFFICIAL_FILENAMES, load_malecns_tables
from .validation import make_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate locally downloaded MaleCNS v1.0 Feather tables")
    parser.add_argument("--data-dir", default="data/raw", type=Path)
    args = parser.parse_args()
    neurons, edges = load_malecns_tables(args.data_dir)
    report = make_report(neurons, edges)
    print(json.dumps({"data_dir": str(args.data_dir), "official_files": OFFICIAL_FILENAMES, **report.as_dict()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
