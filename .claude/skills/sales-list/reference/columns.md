# 列定義と抽出ルール

Excel の各シートは同じ 19 列。`scripts/export_xlsx.py` の `COLUMNS` が唯一の定義。

| 列 | enriched キー | 取得元 / ルール |
|---|---|---|
| 会社名 | company | Google Maps のリスト表示名 / 求人ボックスの掲載社名 |
| 業種/カテゴリ | category | Google Maps のカテゴリ (塗装工, 自動車整備工場 …) |
| 電話番号 | phone | Google Maps の電話 → 無ければ HP の `tel:` リンク / TEL 表記 |
| メールアドレス | email | HP の `mailto:` / 本文の `xxx@yyy` (＠, [at] 表記も復元)。画像や example/noreply は除外。複数あれば先頭。 |
| お問い合わせページ | contact_url | HP 内リンクで「お問い合わせ / contact / inquiry」に一致するもの |
| HP URL | website | Google Maps の「ウェブサイト」リンク。SNS・ポータル (goo-net, 食べログ, エキテン等) は HP とみなさず巡回しない (`common.GENERIC_DOMAINS`) |
| 企業説明(サービス内容) | description | Claude が `descriptions.json` に書いた要約。未作成なら meta description → 事業内容 → 本文先頭段落 の暫定値 |
| 代表者名 | representative | ①会社概要の「代表者 / 代表取締役 / 代表税理士 / 所長 …」行 (肩書き除去) → ②本文の『代表 山田太郎』形式の行 → ③『山田太郎税理士事務所』のような個人名事務所は名称から取り「（事務所名より推定）」を付ける。地名・法人名らしいものは付けない |
| 本社住所 | hq_address | 会社概要の「本社 / 所在地 / 住所 / 本店」行。複数住所が並ぶ場合は最初の 1 件、残りは拠点列へ。無ければ Google Maps の住所 |
| 拠点・子会社・支店 | branches | 「支店 / 営業所 / 拠点 / 事業所 / 工場 / 子会社 / グループ会社 / 店舗」行のうち住所らしいもの (〒 or 都道府県 or 市区町村を含む) を「キー：値 / キー：値」で連結 |
| 資本金 | capital | 「資本金」行 |
| 設立 | established | 「設立 / 創業 / 創立」行 |
| 従業員数 | employees | 「従業員 / 社員数」行 |
| 事業内容(HP原文) | business_raw | 「事業内容 / 業務内容 / 主な事業 / サービス内容」行の原文 (400 字まで) |
| Google Maps評価 | rating | 「4.5 つ星」 |
| Google Maps URL | maps_url | place URL |
| 取得元 | source | Google Maps / 求人ボックス |
| 検索クエリ | query | 「塗装業 東京都」 |
| 取得日 | fetched_at | export 実行日 |

## HP 巡回の範囲 (enrich.py)
1. トップページ
2. 会社概要ページ (リンク文言/URL が 会社概要・企業情報・about・company・profile 等) 最大 2 ページ
3. お問い合わせページ 1 ページ

各ページは `scripts/extract_company.js` で `table th/td`・`dl dt/dd`・「キー：値」行 を key/value 化し、Python 側で列に振り分ける。画像・フォント・メディアはブロックして高速化。

## 重複判定 (common.dedup_keys)
次のいずれかが既存行と一致したら重複 → 保存しない。
- `name:` 会社名を NFKC 正規化 → 小文字 → 法人格 (株式会社, (株), ㈱, 有限会社 …) と空白・記号を除去
- `dom:` HP のドメイン (www. 除去)。ポータル/SNS ドメインはキーにしない
- `tel:` 電話番号の数字のみ (9〜11 桁)

突き合わせ先は **出力ブックの全シート** (`会社名` ヘッダーを持つシート) と、同一 run 内の候補。
`run.py collect` は開始時に既知企業を `known.json` に書き出し、検索段階で除外するので、HP 巡回の無駄が出ない。

## 求人ボックスの扱い
求人ボックスは会社名・勤務地・職種しか持たないため、社名 + 市区町村で Google Maps を検索し、名前が一致 (正規化後に包含) した 1 件から 住所/電話/HP を補う。一致しなければ社名と検索クエリだけの行になり、HP 項目は空欄。
- URL 形式: `https://xn--pckua2a7gp15o89zb.com/<キーワード>の仕事-<エリア>?pg=N` (1 ページ約 25 求人)
- カード: `.p-result_card--ver1` / 社名 `.p-result_companyName` / 勤務地 `.p-result_area`
- 「社名非公開」は除外
