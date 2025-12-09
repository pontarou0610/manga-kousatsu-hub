#!/usr/bin/env python3
"""
Fix permalink structure in all madan-no-ichi article links
Hugo permalink: /posts/:year/:month/:slug/
Wrong: /posts/madan-no-ichi/2025/12/slug/
Correct: /posts/2025/12/slug/
"""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
MADAN_DIR = ROOT_DIR / "content" / "posts" / "madan-no-ichi"


def fix_permalink_structure():
    """Fix all links to use correct permalink structure."""
    print(">> Fixing permalink structure in all links...")
    
    md_files = list(MADAN_DIR.rglob("*.md"))
    modified_count = 0
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Fix: Remove 'madan-no-ichi' from the path
            # Wrong: /posts/madan-no-ichi/2025/12/slug/
            # Correct: /posts/2025/12/slug/
            content = re.sub(
                r'/posts/madan-no-ichi/(\d{4}/\d{2}/[^)]+)',
                r'/posts/\1',
                content
            )
            
            # Also fix any remaining /posts/madan-no-ichi/ references (without year/month)
            # This should now point to tags page
            content = re.sub(
                r'\]\(/posts/madan-no-ichi/\)',
                r'](/tags/madan-no-ichi/)',
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
    fix_permalink_structure()
