"""
Run glossary extraction for all maintained series.

Usage:
  python scripts/update_all_glossaries.py
"""
import subprocess
import sys
from pathlib import Path


SERIES = [
    "madan-no-ichi",
    "heavenly-delusion",
    "dandadan",
]


def main() -> int:
    root = Path(__file__).resolve().parent
    extractor = root / "extract_terms.py"
    if not extractor.exists():
        print(f"[ERROR] extract_terms.py not found at {extractor}", file=sys.stderr)
        return 1

    for series in SERIES:
        cmd = [sys.executable, str(extractor), "--series", series]
        print(f"[INFO] extracting terms for {series} ...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[ERROR] failed for {series}: {result.stderr}", file=sys.stderr)
            return result.returncode
        print(result.stdout.strip())

    print("[INFO] glossary extraction completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
