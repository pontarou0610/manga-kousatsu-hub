# manga-kousatsu-hub

人気漫画の考察（ネタバレ注意）を Hugo + GitHub Pages で公開するプロジェクトです。GitHub Actions が公式 RSS を巡回し、新着検知→Hugo 記事生成→gh-pages へのデプロイまでを自動化します。

> **置換が必要なプレースホルダ**
>
> - `YOUR_AMAZON_TAG`
> - `YOUR_RAKUTEN_PARAMS`

## 構成

```
.
├─ config.toml
├─ content/
│  ├─ posts/        # 生成済み記事
│  └─ drafts/       # 退避用ドラフト
├─ data/
│  ├─ series.yaml   # 作品ごとの設定
│  ├─ state.json    # 取得済みハッシュ
│  └─ glossary/     # 作品別用語リスト
├─ layouts/
│  ├─ _default/baseof.html
│  ├─ _default/single.html
│  ├─ partials/affiliate_notice.html
│  └─ shortcodes/{spoiler, affbox}.html
├─ scripts/
│  ├─ generate_posts.py
│  ├─ utils.py
│  └─ requirements.txt
├─ static/ogp/      # Pillow が出力する OGP
├─ templates/post.md.j2
└─ .github/workflows/build.yml
```

## セットアップ

1. **Hugo / Python**
   - Hugo Extended 最新版と Python 3.11 以上をインストールします。
2. **依存パッケージ**

   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r scripts/requirements.txt
   ```

3. **API キー (.env)**

   ルートに `.env` を作成し、少なくとも `OPENAI_API_KEY` を設定します。任意で `OPENAI_MODEL`（既定: `gpt-4o-mini`）と Pexels 画像取得用の `PEXELS_API_KEY` も指定できます。

   ```
   OPENAI_API_KEY=sk-xxxx
   OPENAI_MODEL=gpt-4o-mini
   PEXELS_API_KEY=your_pexels_token
   ```

4. **Hugo 設定**
   - `config.toml` の `baseURL` を `https://pontarou0610.github.io/manga-kousatsu-hub/` に変更。
   - Amazon / Rakuten のトラッキング情報を `YOUR_AMAZON_TAG`, `YOUR_RAKUTEN_PARAMS` に置き換えます。

5. **作品設定**
   - `data/series.yaml` に作品ごとの RSS、タグ、アフィ情報を追加。
   - `content_modes` に `spoiler`（トグル内ネタバレ）、`insight`（ネタバレ無し考察）、`glossary`（用語集）を列挙します。
   - `fallback_topics` を設定すると、RSS新着が無い日でもそのトピックをテーマにしたインサイト記事が自動生成されます。
   - `manual: true` の作品は `release_day` 当日にドラフトのみ生成し、公開は手動で行います。
6. **用語集データ**
   - `data/glossary/<series-slug>.yaml` に `terms` 配列（用語・読み・説明・参考）を追加します。`glossary` モードが有効な作品で参照されます。
   - 参考情報は公式サイトだけでなく、Wikipedia など信頼できる公開資料も明記してください。用語は3件以上から始め、追記するたびに上から順に自動公開され、1回のビルドで少しずつ増えていきます。

7. **動作確認**

   ```bash
   python scripts/generate_posts.py
   hugo --minify
   ```

   `content/posts/` に記事、`static/ogp/` に OGP が生成されれば成功です。

## 生成フロー

1. `data/series.yaml` の RSS から feedparser で新着を取得。
2. URL/タイトルのハッシュを `data/state.json` に保存し、重複をスキップ。
3. OpenAI API（`scripts/utils.py`）でネタバレ記事用／ネタバレ無し考察用それぞれのJSONを生成。RSS新着が無い場合も `fallback_topics` をもとにインサイト記事を自動作成します。APIキーが無い場合はテンプレで補完。
4. Jinja テンプレート `templates/post_spoiler.md.j2` / `post_insight.md.j2` / `post_glossary.md.j2` を使って記事を出力。
5. `content_modes` に `glossary` が含まれる作品は `data/glossary/<slug>.yaml` を基に用語集を再生成。
6. Pexels API（`PEXELS_API_KEY`）でヒーロー画像を取得できれば本文冒頭に挿入。
7. Pillow で `static/ogp/YYYYMMDD_slug.png` を生成し、フロントマター `images` に設定。
8. 失敗時は `content/drafts/` へ退避し、処理を続行。

> 参考実装: OpenAI を使った原稿生成フローは `C:\work\hugo-sites\my-affiliate-site1` の `scripts/generate_post.py` をベースに、漫画考察向けに最適化しています。

### 記事タイプ

- `spoiler`: ネタバレ詳細あり。`{{< spoiler >}}` で折りたたみ表示し、重要伏線・次回予想を記載。
- `insight`: ネタバレ無しの分析記事。テーマ・キャラクター視点・行動プランを提示。
- `glossary`: `data/glossary/<slug>.yaml` の terms を読み込んで用語解説ページを生成。シリーズごとのハブとして利用します。

## GitHub Actions

`.github/workflows/build.yml` は以下で起動します。

- `schedule`: `0 0,9,18 * * *`
- `workflow_dispatch`
- `push`（`main`）

処理フロー: checkout → setup-python → 依存インストール → `python scripts/generate_posts.py` → `hugo --minify` → `peaceiris/actions-gh-pages@v3` で `gh-pages` ブランチにデプロイ。

## 収益設計

- **現在**: Amazon / Rakuten のアフィリエイトのみ。記事冒頭に `affiliate_notice` を差し込み、`affbox` ショートコードで商品ボタンを表示。すべて `rel="sponsored noopener"`。
- **将来**: `series.yaml` の `affiliates.others` に `{ name, url }` を追加するだけで本文末に公式配信ストアを列挙。`priority` 配列で表示順を制御し、漫画配信アフィを柔軟に拡張できます。

## 法的・運用上の注意

- **画像**: `static/ogp/` で自動生成するテキスト OGP のみ。版権画像は取得・保存しない。
- **引用**: 必要最小限で出典を明示し、主従関係を守る（長文セリフは禁止）。
- **ネタバレ配慮**: タイトルに「ネタバレ注意」を入れ、本文冒頭はネタバレ無し。詳細は `spoiler` トグル内に限定。
- **情報源**: 公式 RSS / 公開情報のみを利用し、利用規約に反するスクレイピングは禁止。
- **削除依頼**: Issue または `contact@example.com`（適宜変更）で受け付け、迅速に対応。

## 運用ヒント

- `data/state.json` を削除すると全フィードを再処理するため、通常はコミットして保持します。
- `manual: true` の作品は発売想定日にドラフトを生成し、公式配信確認後に `draft: false` に切り替えて公開します。
- `templates/post.md.j2` を編集すれば、ネタバレ配慮の枠組みを保ったまま構成を調整できます。

## ライセンス

MIT License（`LICENSE` 参照）。
