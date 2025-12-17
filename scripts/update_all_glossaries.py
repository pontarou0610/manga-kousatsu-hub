"""
Run glossary extraction for all maintained series.

Usage:
  python scripts/update_all_glossaries.py
"""
import os
import subprocess
import sys
from pathlib import Path


SERIES = [
    "madan-no-ichi",
    "heavenly-delusion",
    "dandadan",
]


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    repo_root = scripts_dir.parent
    extractor = scripts_dir / "extract_terms.py"
    if not extractor.exists():
        print(f"[ERROR] extract_terms.py not found at {extractor}", file=sys.stderr)
        return 1

    strict_missing = os.environ.get("GLOSSARY_STRICT_MISSING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    failed: list[str] = []
    for series in SERIES:
        series_dir = repo_root / "content" / "posts" / series
        if not series_dir.is_dir():
            missing_path = series_dir
            try:
                missing_path = series_dir.relative_to(repo_root)
            except ValueError:
                pass
            msg = f"[WARN] skipping {series}: series folder not found: {missing_path.as_posix()}"
            if strict_missing:
                print(msg.replace("[WARN]", "[ERROR]"), file=sys.stderr)
                failed.append(series)
            else:
                print(msg, file=sys.stderr)
            continue

        cmd = [sys.executable, str(extractor), "--series", series]
        print(f"[INFO] extracting terms for {series} ...")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root)
        if result.returncode != 0:
            print(f"[ERROR] failed for {series}: {result.stderr}", file=sys.stderr)
            failed.append(series)
            continue
        if result.stdout.strip():
            print(result.stdout.strip())

    if failed:
        print(f"[ERROR] glossary extraction failed for: {', '.join(failed)}", file=sys.stderr)
        return 1

    print("[INFO] glossary extraction completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
