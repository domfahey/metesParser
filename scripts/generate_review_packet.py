#!/usr/bin/env python3
"""Generate review packets for professional audit of ground truth data.

Reads all *.ground_truth.json files from sample_deeds/ and generates
self-contained HTML review worksheets in sample_deeds/review_packets/.

Usage:
    uv run python scripts/generate_review_packet.py
    uv run python scripts/generate_review_packet.py --source sample_deeds --output sample_deeds/review_packets
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from metesparser.review_packet import generate_all_packets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate HTML review packets from ground truth JSON files."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).parent.parent / "sample_deeds",
        help="Directory containing .ground_truth.json files (default: sample_deeds/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for HTML packets (default: <source>/review_packets/)",
    )
    args = parser.parse_args()

    source_dir = args.source.resolve()
    output_dir = (args.output or source_dir / "review_packets").resolve()

    if not source_dir.is_dir():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    print(f"Source: {source_dir}")
    print(f"Output: {output_dir}")

    paths = generate_all_packets(source_dir, output_dir)

    if not paths:
        print("No ground truth files found.")
        sys.exit(0)

    print(f"\nGenerated {len(paths)} review packets:")
    for p in paths:
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
