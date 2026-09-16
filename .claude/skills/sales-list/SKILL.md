---
name: sales-list
description: Google Maps と求人ボックスから「業種 × エリア」で企業を収集し、各社HPを巡回して 会社名/電話/メール/問い合わせページ/代表者/本社住所/拠点/資本金/企業説明 を抽出、業種名のシートで Excel(営業リスト.xlsx)に追記する営業リスト作成スキル。既存ブック全シートと突き合わせて重複企業は保存しない。「営業リストを作って」「〇〇業(〇〇エリア)のリスト100件」「リード/見込み客リスト収集」や /sales-list で使用。ヘッドレス Playwright(Python)で収集し、Playwright MCP は検証・補完に使う。
---

# 営業リスト作成 (sales-list)

業種キーワードとエリアから **新規企業 N 件（既定 100）** を集め、HP を読んで営業に必要な項目を埋め、`営業リスト.xlsx` の **業種名シート** に追記する。収集・抽出・Excel 出力はスクリプト、**企業説明文の執筆と不足時の再検索判断は Claude** が行う。

- スクリプト: `.claude/skills/sales-list/scripts/` (以下 `$S`)。実行は Python 3 + playwright + openpyxl (導入済み)。
- 使い方の全体像: [README.md](README.md) / 列定義・抽出ルール・重複判定: [reference/columns.md](reference/columns.md)
- 失敗時の対処 / Playwright MCP での手動補完: [reference/troubleshooting.md](reference/troubleshooting.md)

## ワークフロー

### 1. 条件を確定する
依頼文（`/sales-list <業種> [エリア] [件数] [シート名: ..] [出力先: ..]` の自由文引数、または通常の依頼文）から次を決める。業種が無い場合だけ質問し、それ以外は既定で進めて最初の報告で明示する。「続きを <run-dir> から再開」とあれば `--run-dir` と `--resume` を付ける。

| 項目 | 既定 | 例 |
|---|---|---|
| `--query` 業種キーワード | 必須 | 塗装業 / 歯科医院 / 税理士事務所 |
| `--area` エリア | なし(全国) ※カンマ区切りで複数可 | 東京都 / 新宿区,渋谷区 |
| `--target` 件数 | 100 | |
| `--sheet` シート名 | query と同じ | 塗装業_東京 |
| `--xlsx` 出力先 | カレントの `営業リスト.xlsx` (このプロジェクトでは `/Users/kohei/dev/cloudwin/sales-automation/営業リスト.xlsx`) | |

### 2. 収集 + HP 巡回 (`collect`)
100 件で 5〜15 分かかるので **バックグラウンド実行**し、ログを追う。

```bash
cd /Users/kohei/dev/cloudwin/sales-automation
S=.claude/skills/sales-list/scripts; mkdir -p output
nohup python3 $S/run.py collect --query "塗装業" --area "東京都" --target 100 --sheet "塗装業" --xlsx 営業リスト.xlsx > output/collect.log 2>&1 &
```
- 既存 Excel の全シートを読み、既知企業は候補段階で除外 → **新規 target 件**を目指す。
- 順序: Google Maps (最大約120件/検索) → 足りなければ求人ボックス (社名を集め Google Maps で所在地/HP を解決)。
- 成果物: `output/<sheet>_<日付>/candidates.json` → `enriched.json` → `summary.json` (件数・項目充足率・`shortfall`)。
- 完了条件: `summary.json` が書かれ、`enriched` が target 以上。

### 3. 不足なら広げて再収集
`shortfall > 0` のとき、同じ `--run-dir` に `--resume` で追記する。**enriched が target に達するまで**繰り返し、それでも届かなければ理由（ヒット数の上限）を添えて報告する。
1. エリア分割: `--area "新宿区,渋谷区,港区,..."`（都道府県 → 市区、市 → 隣接市）
2. 同義語: `--query "外壁塗装"`, `"塗装工事"`, `--kb-query "塗装工"`
3. ソース指定: `--sources kb` だけ追加、など

```bash
python3 $S/run.py collect --query "塗装業" --area "新宿区,渋谷区,港区" --target 100 --sheet "塗装業" --run-dir output/塗装業_2026-09-16 --resume
```

### 4. 企業説明を書く (Claude の担当)
`python3 $S/show_for_summary.py output/<run-dir> --offset 0 --limit 25` で 25 社ずつ表示し、`output/<run-dir>/descriptions.json` に `{"会社名": "説明文"}` を書く。
- 1〜2 文・80〜160 字。**何をしている会社か → 主なサービス/強み → 対象顧客や地域**。HP 原文の丸写しではなく営業担当が 5 秒で掴める要約にする。
- HP 不達・情報なしの会社は `""`（空欄のまま）。
- 完了条件: enriched.json の `hp_status == "ok"` の全社が descriptions.json に載っている。

### 5. Excel 出力 (`export`)
```bash
python3 $S/run.py export --run-dir output/塗装業_2026-09-16 --sheet "塗装業" --xlsx 営業リスト.xlsx
```
`--limit 100` で追加件数を target ちょうどに揃えられる (既定は enriched 全件)。stdout の JSON (`added` / `duplicates_skipped` / `sheet_total_rows`) を報告に使う。既存ブック全シートと **会社名(法人格・空白除去) / HP ドメイン / 電話番号** のいずれか一致で重複扱いにして保存しない。

### 6. 検証と報告
- `openpyxl` でシートの行数と、電話/メール/HP/代表者/資本金の充足数を数える。
- Playwright MCP が使える場合は無作為 2〜3 社の HP を `browser_navigate` で開き、電話番号と代表者が一致するか目視確認する（不一致があれば該当行を修正して再保存）。
- 報告: シート名、追加件数、重複除外件数、各項目の充足率、届かなかった場合はその理由と次の一手。

## 注意
- Google Maps の結果は 1 クエリ約 120 件が上限。100 件の新規企業が要る場合はエリア分割が前提。
- 収集元に情報が無い項目は空欄のままにする（推測で埋めない）。
- 電話番号 `0078-` / `0800-` 始まりは Google 経由の転送番号のことがある。そのまま記載し、備考で触れる必要はない。
