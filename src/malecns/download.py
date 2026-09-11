"""Explicit downloader for official MaleCNS v1.0 Feather files."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.request import urlretrieve

from .loader import OFFICIAL_FILENAMES

BASE_URL = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome"


def download_file(name: str, output_dir: str | Path = "data/raw") -> Path:
    if name not in OFFICIAL_FILENAMES:
        raise ValueError(f"Unknown official file key {name!r}; choose from {sorted(OFFICIAL_FILENAMES)}")
    destination = Path(output_dir) / OFFICIAL_FILENAMES[name]
    destination.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(f"{BASE_URL}/{destination.name}", destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Download selected official MaleCNS v1.0 Feather files")
    parser.add_argument("names", nargs="+", choices=sorted(OFFICIAL_FILENAMES), help="files to download; connectivity is about 1.1 GB")
    parser.add_argument("--output-dir", default="data/raw", type=Path)
    args = parser.parse_args()
    for name in args.names:
        print(download_file(name, args.output_dir))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
