import argparse
import re
import sys
from pathlib import Path

import yaml


TERM_PATTERN = re.compile(
    r"{{<\s*term\s+([^>]+?)>}}(.*?){{<\s*/term\s*>}}",
    re.IGNORECASE | re.DOTALL,
)
ATTR_PATTERN = re.compile(r'([a-zA-Z0-9_-]+)\s*=\s*"([^"]*)"')


def parse_attrs(attr_block: str) -> dict:
    attrs = {}
    for key, value in ATTR_PATTERN.findall(attr_block):
        attrs[key] = value
    return attrs


def extract_terms_from_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    terms = []
    for match in TERM_PATTERN.finditer(text):
        attrs = parse_attrs(match.group(1))
        name = attrs.get("name")
        if not name:
            continue
        term = {
            "term": name,
            "reading": attrs.get("reading", ""),
            "first_appear": attrs.get("first", ""),
            "desc": match.group(2).strip(),
            "source": str(path.resolve().relative_to(Path.cwd())),
        }
        terms.append(term)
    return terms


def merge_terms(terms: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for term in terms:
        key = term["term"]
        existing = merged.get(key)
        if not existing:
            merged[key] = term
            continue
        if not existing.get("reading") and term.get("reading"):
            existing["reading"] = term["reading"]
        if not existing.get("first_appear") and term.get("first_appear"):
            existing["first_appear"] = term["first_appear"]
        if not existing.get("desc") and term.get("desc"):
            existing["desc"] = term["desc"]
    return list(merged.values())


def render_items(merged_terms: list[dict]) -> list[dict]:
    items = []
    for term in sorted(merged_terms, key=lambda t: t["term"]):
        item = {"term": term["term"]}
        if term.get("reading"):
            item["reading"] = term["reading"]
        if term.get("desc"):
            item["desc"] = " ".join(term["desc"].split())
        if term.get("first_appear"):
            item["first_appear"] = term["first_appear"]
        items.append(item)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract glossary terms from term shortcode")
    parser.add_argument(
        "--series",
        required=True,
        help="series folder name under content/posts (e.g. madan-no-ichi)",
    )
    parser.add_argument(
        "--output",
        help="output path (default: data/glossary/<series>.yaml)",
    )
    args = parser.parse_args()

    content_root = Path("content/posts") / args.series
    if not content_root.exists():
        print(f"[ERROR] series folder not found: {content_root}", file=sys.stderr)
        return 1

    files = sorted(content_root.rglob("*.md"))
    all_terms: list[dict] = []
    for file_path in files:
        all_terms.extend(extract_terms_from_file(file_path))

    merged_terms = merge_terms(all_terms)
    items = render_items(merged_terms)

    output_path = Path(args.output) if args.output else Path("data/glossary") / f"{args.series}.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump({"items": items}, output_path.open("w", encoding="utf-8"), allow_unicode=True, sort_keys=False)

    print(f"Processed {len(files)} markdown files, found {len(all_terms)} shortcode hits.")
    print(f"Saved {len(items)} unique terms to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
