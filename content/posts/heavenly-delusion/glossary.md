---
title: 天国大魔境 用語集
date: 2025-12-02T00:11:50+00:00
series: 天国大魔境
chapter: 用語集
article_variant: glossary
slug: heavenly-delusion-glossary
tags:
  - 用語解説
  - SF
  - ミステリー
  - 月刊誌
draft: false
affiliate_ids:
  amazon: https://www.amazon.co.jp/dp/B07FCHN6XQ?tag=naoto0610-22
  rakuten: https://hb.afl.rakuten.co.jp/ichiba/0d1b5972.6cd44226.0d1b5973.40a5c49e/pc=https%3A%2F%2Fsearch.rakuten.co.jp%2Fsearch%2Fmall%2Fheavenly-delusion%2F&link_type=picttext&ut=eyJwYWdlIjoiaXRlbSIsInR5cGUiOiJwaWN0dGV4dCIsInNpemUiOiIyNDB4MjQwIiwibmFtIjoxLCJuYW1wIjoicmlnaHQiLCJjb20iOjEsImNvbXAiOiJkb3duIiwicHJpY2UiOjEsImJvciI6MSwiY29sIjoxLCJiYnRuIjoxLCJwcm9kIjoxLCJhbXAiOmZhbHNlfQ%3D%3D
  others: []
disclaimer: 壁内外の設定・用語は公式資料を参照し、ネタバレは折りたたみ内に限定します。
images: []
---

## ???????????
- {< term name="??" reading="????" first="?1?" >}????????????????????{< /term >}
- {< term name="??" reading="????" first="?1?" >}?????????????????????{< /term >}
- {< term name="??" reading="??" first="?1?" >}???????????????????????{< /term >}
- {< term name="???" reading="???" first="?1?" >}??????????????????????{< /term >}


天国大魔境に登場する重要な用語をまとめて紹介します。ショートコードで記事にマークした用語を自動抽出し、随時更新します。

{{ $raw := .Site.Data.glossary.heavenly_delusion }}
{{ $items := cond (isset $raw "items") $raw.items $raw }}
{{ if not $items }}
用語データが未登録です。データファイル `data/glossary/heavenly-delusion.yaml` を更新してください。
{{ else }}
## 用語リスト
{{ range $items }}
### {{ .term }}{{ with .reading }}（{{ . }}）{{ end }}
- 説明: {{ .desc | default "準備中" }}
{{ with .first_appear }}- 初登場: {{ . }}{{ end }}
{{ end }}
{{ end }}