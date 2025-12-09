#!/usr/bin/env python3
"""Check slugs in madan-no-ichi posts"""

import frontmatter
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
MADAN_DIR = ROOT_DIR / "content" / "posts" / "madan-no-ichi"

md_files = sorted(list(MADAN_DIR.rglob("*.md")))

print("Filename -> Slug")
print("=" * 80)

for md_file in md_files[:20]:
    try:
        with open(md_file, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        
        slug = post.get('slug', 'NO SLUG')
        chapter = post.get('chapter', 'NO CHAPTER')
        print(f"{md_file.name:60} -> {slug}")
        
    except Exception as e:
        print(f"{md_file.name:60} -> ERROR: {e}")
