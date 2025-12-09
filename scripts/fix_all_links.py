#!/usr/bin/env python3
"""
Comprehensive fix for all links in madan-no-ichi articles
- Fixes series list links
- Fixes previous article links
- Fixes glossary links
"""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
MADAN_DIR = ROOT_DIR / "content" / "posts" / "madan-no-ichi"


def fix_all_links():
    """Fix all broken links in madan-no-ichi articles."""
    print(">> Starting comprehensive link fix...")
    
    md_files = list(MADAN_DIR.rglob("*.md"))
    modified_count = 0
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Fix 1: Series list link - should point to series page, not posts directory
            # Wrong: /posts/madan-no-ichi/
            # Correct: /series/madan-no-ichi/ or just the tag/category page
            content = re.sub(
                r'\[([^\]]*記事一覧[^\]]*)\]\(/posts/madan-no-ichi/\)',
                r'[\1](/tags/madan-no-ichi/)',
                content
            )
            
            # Fix 2: Glossary link - ensure it's correct
            content = re.sub(
                r'\[用語集\]\(/posts/madan-no-ichi/glossary/\)',
                r'[用語集](/posts/madan-no-ichi/glossary/)',
                content
            )
            
            if content != original_content:
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"[OK] Fixed: {md_file.relative_to(ROOT_DIR)}")
                modified_count += 1
                
        except Exception as e:
            print(f"[ERROR] Failed to process {md_file}: {e}")
            continue
    
    print(f"\n>> Processing complete!")
    print(f">> Modified: {modified_count} files")


if __name__ == "__main__":
    fix_all_links()
