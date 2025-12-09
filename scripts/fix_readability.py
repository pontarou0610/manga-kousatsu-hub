#!/usr/bin/env python3
"""
既存の記事を読みやすく修正するスクリプト
句点の後に改行を追加して、読みやすさを向上させます。
"""

import re
from pathlib import Path
import frontmatter

# パス設定
ROOT_DIR = Path(__file__).parent.parent
CONTENT_DIR = ROOT_DIR / "content" / "posts"


def add_line_breaks_after_periods(text: str) -> str:
    """
    句点（。）の後に改行を追加する。
    ただし、既に改行がある場合や、特殊なケースは除外。
    """
    if not text:
        return text
    
    # 既に句点の後に改行がある場合はスキップ
    if re.search(r'。\n', text):
        return text
    
    # 句点の後に改行を追加（ただし、既に改行がある場合や文末は除く）
    # パターン: 。の後に空白や文字が続く場合
    result = re.sub(r'。(?=[^\n])', '。\n', text)
    
    return result


def process_markdown_file(file_path: Path) -> bool:
    """
    Markdownファイルを処理して、句点の後に改行を追加する。
    
    Returns:
        True if file was modified, False otherwise
    """
    try:
        # ファイルを読み込み
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)
        
        modified = False
        
        # 本文を処理
        if post.content:
            new_content = add_line_breaks_after_periods(post.content)
            if new_content != post.content:
                post.content = new_content
                modified = True
        
        # フロントマターのdescriptionを処理
        if 'description' in post.metadata:
            new_desc = add_line_breaks_after_periods(post.metadata['description'])
            if new_desc != post.metadata['description']:
                post.metadata['description'] = new_desc
                modified = True
        
        # 変更があった場合のみ保存
        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(frontmatter.dumps(post))
            print(f"[OK] Modified: {file_path.relative_to(ROOT_DIR)}")
            return True
        else:
            print(f"[SKIP] No changes: {file_path.relative_to(ROOT_DIR)}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Failed to process {file_path}: {e}")
        return False


def main():
    """メイン処理"""
    print(">> Starting to process existing articles...")
    
    # すべてのMarkdownファイルを検索
    md_files = list(CONTENT_DIR.rglob("*.md"))
    print(f">> Found {len(md_files)} markdown files")
    
    modified_count = 0
    
    for md_file in md_files:
        if process_markdown_file(md_file):
            modified_count += 1
    
    print(f"\n>> Processing complete!")
    print(f">> Modified: {modified_count} files")
    print(f">> Skipped: {len(md_files) - modified_count} files")


if __name__ == "__main__":
    main()
