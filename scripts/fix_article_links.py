#!/usr/bin/env python3
"""
Fix broken article links in madan-no-ichi posts
Reads frontmatter slugs and fixes all "前回のネタバレ" links
"""

import re
import frontmatter
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).parent.parent
MADAN_DIR = ROOT_DIR / "content" / "posts" / "madan-no-ichi"


def get_slug_from_file(file_path: Path) -> str:
    """Extract slug from frontmatter."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
            return post.get('slug', '')
    except Exception as e:
        print(f"[ERROR] Failed to read {file_path}: {e}")
        return ''


def build_slug_map():
    """Build a map of chapter numbers to slugs."""
    slug_map = {}
    
    # Find all markdown files
    md_files = list(MADAN_DIR.rglob("*.md"))
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                post = frontmatter.load(f)
                
            slug = post.get('slug', '')
            chapter = post.get('chapter', '')
            
            # Extract chapter number
            match = re.search(r'第(\d+)話', chapter)
            if match:
                chapter_num = int(match.group(1))
                slug_map[chapter_num] = {
                    'slug': slug,
                    'file': md_file,
                    'date': post.get('date', '')
                }
                
        except Exception as e:
            continue
    
    return slug_map


def fix_article_links():
    """Fix all broken article links."""
    print(">> Building slug map...")
    slug_map = build_slug_map()
    
    print(f">> Found {len(slug_map)} articles with chapter numbers")
    
    # Find all markdown files again
    md_files = list(MADAN_DIR.rglob("*.md"))
    modified_count = 0
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Find all "前回のネタバレ" links
            pattern = r'前回のネタバレ[：:]\s*\[([^\]]+)\]\(/posts/madan-no-ichi/[^\)]+\)'
            
            def replace_link(match):
                link_text = match.group(1)
                
                # Extract chapter number from link text
                chapter_match = re.search(r'第(\d+)話', link_text)
                if not chapter_match:
                    return match.group(0)  # No change
                
                prev_chapter = int(chapter_match.group(1))
                
                # Look up the correct slug
                if prev_chapter in slug_map:
                    correct_slug = slug_map[prev_chapter]['slug']
                    date_obj = slug_map[prev_chapter]['date']
                    
                    # Extract year and month
                    if isinstance(date_obj, datetime):
                        year = date_obj.year
                        month = f"{date_obj.month:02d}"
                    elif isinstance(date_obj, str):
                        # Try to parse date string
                        try:
                            date_obj = datetime.fromisoformat(date_obj.replace('+00:00', ''))
                            year = date_obj.year
                            month = f"{date_obj.month:02d}"
                        except:
                            # Fallback to 2025/12
                            year = 2025
                            month = "12"
                    else:
                        year = 2025
                        month = "12"
                    
                    new_link = f'前回のネタバレ: [{link_text}](/posts/madan-no-ichi/{year}/{month}/{correct_slug}/)'
                    return new_link
                
                return match.group(0)  # No change if slug not found
            
            content = re.sub(pattern, replace_link, content)
            
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
    fix_article_links()
