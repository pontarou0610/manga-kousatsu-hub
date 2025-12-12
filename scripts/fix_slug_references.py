#!/usr/bin/env python3
"""
Fix incorrect slug references in manga-kousatsu-hub
Corrects maotoko-no-ichi to madan-no-ichi in all files
"""

import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
CONTENT_DIR = ROOT_DIR / "content" / "posts"


def fix_slug_references(file_path: Path) -> bool:
    """
    Fix incorrect slug references in a file.
    
    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Fix /posts/maotoko-no-ichi/ to /posts/madan-no-ichi/
        content = content.replace('/posts/maotoko-no-ichi/', '/posts/madan-no-ichi/')
        
        # Fix full URLs with maotoko-no-ichi
        content = content.replace(
            'https://pontarou0610.github.io/manga-kousatsu-hub/posts/maotoko-no-ichi/',
            'https://pontarou0610.github.io/manga-kousatsu-hub/posts/madan-no-ichi/'
        )
        
        # Fix malformed glossary links
        # Pattern: [用語集](? [用語集: [用語集](](：[用語集](URL)))
        # Should be: [用語集]({{< ref "posts/madan-no-ichi/glossary" >}})
        malformed_pattern = r'\[用語集\]\(\?\s*\[用語集:\s*\[用語集\]\(\]\(：\[用語集\]\(https://pontarou0610\.github\.io/manga-kousatsu-hub/posts/[^/]+/glossary/\)\)\)'
        content = re.sub(malformed_pattern, '[用語集]({{< ref "posts/madan-no-ichi/glossary" >}})', content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[OK] Fixed: {file_path.relative_to(ROOT_DIR)}")
            return True
        else:
            return False
            
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
        return False


def main():
    """Main execution"""
    print(">> Starting to fix slug references...")
    
    # Find all markdown files
    md_files = list(CONTENT_DIR.rglob("*.md"))
    print(f">> Found {len(md_files)} markdown files")
    
    modified_count = 0
    
    for md_file in md_files:
        if fix_slug_references(md_file):
            modified_count += 1
    
    print(f"\n>> Processing complete!")
    print(f">> Modified: {modified_count} files")


if __name__ == "__main__":
    main()
