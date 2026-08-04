# Wiki RAG Search

25個の界隈Wiki全部をクロールして作った、**AIのRAG (Retrieval-Augmented Generation) 用オンライン検索エンジン**。
SearXNG とは完全に別物の、独立した全文検索サービス。バックエンドは [Meilisearch](https://www.meilisearch.com/)。

- **API エンドポイント**: `https://wiki-search.hikamer.f5.si`
- **インデックス名**: `wiki_rag`
- **検索専用キー**: `eb1f1f81c3bbcf6ecc544ba34b31c98007de0db43762af2ffcf26171ee8ab1b1` (search専用・wiki_rag限定・読み取りのみ)
- **デモ検索ページ**: https://maebahesioru.github.io/wiki-rag-search/ (GitHub Pages)

## 収録Wiki (25)

| key | Wiki | プラットフォーム |
|---|---|---|
| hikamers | ヒカマーwiki (hikamers.net) | MediaWiki (PoW認証突破) |
| atw_hikamer | ヒカマーwiki (atwiki) | atwiki |
| atw_hikamerswiki6 | ヒカマーwiki6 | atwiki |
| seesaa_hikakinmania | Hikakin_Mania Wiki | seesaa |
| seesaa_hikakin_mania | Hikakin_Mania Wiki (2) | seesaa |
| atw_hikasei_mania | hikasei_mania | atwiki |
| ww_huromani | Hikamer Wiki | wikiwiki |
| ww_hika_mer53 | ヒカマーwiki | wikiwiki |
| fandom_hikakin | HIKAKIN Wiki | Fandom (MediaWiki) |
| wiki3_hikamani | Re:Hikakin_mania創作wiki | wiki3.jp |
| memo_hikakinmania | hikakin-mania | memo.wiki |
| fandom_tsuihaikaiwai | ツイ廃界隈 Wiki | Fandom (MediaWiki) |
| ww_sfxxtdz66 | m / ヒカマーwiki | wikiwiki |
| inmu | 淫ク☆解説Wiki | MediaWiki |
| ww_noire | Xのヒカマニ界隈 Wiki | wikiwiki |
| memo_gaymasuo | gaymasuo | memo.wiki |
| atw_twihigh_tcg | ツイ廃TCG | atwiki |
| atw_tsuihaikaiwai | ツイ廃界隈 @Wiki | atwiki |
| reinoare | 例のアレ辞典 | MediaWiki |
| krsw | 唐澤貴洋Wiki | MediaWiki |
| fandom_otomad | 音MAD Wiki | Fandom (MediaWiki) |
| fc2_youtuber | YouTuberWiki | fc2 |
| fc2_horrorinm | ホラー・ミステリー淫夢Wiki | fc2 |
| yjsnpi | 真夏の夜の淫夢Wiki | MediaWiki |
| atw_cookie_kaisetu | クッキー☆解説Wiki | atwiki |

## RAG からの使い方

### curl

```bash
curl -s -X POST "https://wiki-search.hikamer.f5.si/indexes/wiki_rag/search" \
  -H "Authorization: Bearer $WIKI_SEARCH_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q": "ヒカキン 本名", "limit": 10}'
```

### Python (requests)

```python
import requests

resp = requests.post(
    "https://wiki-search.hikamer.f5.si/indexes/wiki_rag/search",
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    json={"q": "唐澤貴洋 住所", "limit": 5, "attributesToHighlight": ["text"]},
)
for hit in resp.json()["hits"]:
    print(hit["wiki_label"], "|", hit["page_title"], "|", hit["url"])
    print(hit["text"][:300])
```

### LangChain / LlamaIndex

- **LangChain**: `MeilisearchRetriever` / `Meilisearch` vectorstore がそのまま使える
- **LlamaIndex**: `MeilisearchReader` でクエリ実行

### フィルタ例

- 特定Wikiだけ: `{"q": "...", "filter": "wiki = krsw"}`
- 特定Wikiを除外: `{"filter": "wiki != atw_hikamer"}`
- ページタイトル絞り込み: `{"filter": "page_title = ヒカキン"}`

### レスポンス項目

`hits[]` に以下のフィールド: `id`, `wiki`, `wiki_label`, `page_title`, `url`, `namespace`, `text` (チャンク本文), `_formatted` (ハイライト付き)

## 構成

```
web/index.html        デモ検索ページ
crawler/config.py     25Wiki定義
crawler/fetch.py      HTTP + hikamers.net PoWソルバ
crawler/extract.py    HTML/wikitext→テキスト + チャンキング
crawler/adapters.py   プラットフォーム別クローラー
crawler/crawl.py      クロール本体 → corpus/<key>.jsonl
index.py              corpus → Meilisearch インデックス
docker-compose.yml    Meilisearch 本体 (Coolify デプロイ用)
```

## 再クロール手順

```bash
python crawler/crawl.py            # 全Wiki (完了済みのものはスキップ)
python crawler/crawl.py --force    # 全部やり直し
python crawler/crawl.py --wikis krsw,yjsnpi   # 特定Wikiのみ
python index.py --meili https://wiki-search.hikamer.f5.si --key $MASTER_KEY
```

チャンクは `id` ベースの upsert なので、再実行しても重複しない。
