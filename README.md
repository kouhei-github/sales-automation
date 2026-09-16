# sales-automation

営業リストを自動作成する Claude Code スキル `sales-list` を管理するリポジトリです。
このフォルダで Claude Code を起動すると、プロジェクトスキルとして `/sales-list` が使えます。

## 構成

```
.claude/skills/sales-list/
  SKILL.md              Claude が読む手順書（スラッシュコマンドの引数解釈〜Excel 出力まで）
  README.md             使い方の詳細（スラッシュコマンド、手動実行、オプション、重複ルール）
  scripts/
    run.py              パイプライン本体 (collect / export)
    search_gmaps.py     Google Maps 検索
    search_kyujinbox.py 求人ボックス検索 → Google Maps で所在地・HP を解決
    enrich.py           企業 HP 巡回（メール・代表者・資本金など）
    extract_company.js  HP からの抽出ロジック（Playwright MCP からも利用可）
    export_xlsx.py      Excel 追記と重複除外
    show_for_summary.py 企業説明を書くための要約ビュー
    common.py           共通処理（正規化・重複キー）
  reference/
    columns.md          列定義と抽出ルール
    troubleshooting.md  失敗時の対処、Playwright MCP での手動補完
営業リスト.xlsx           出力先（git 管理外）
output/                  収集の中間ファイル（git 管理外）
```

## 使い方

```
/sales-list 塗装業 東京都 100件
```

詳細は [.claude/skills/sales-list/README.md](.claude/skills/sales-list/README.md) を参照してください。

## 他のプロジェクトからも使いたい場合

ユーザースキルとしてシンボリックリンクを置くと、どのフォルダからでも `/sales-list` が使えます。

```bash
ln -s /Users/kohei/dev/cloudwin/sales-automation/.claude/skills/sales-list ~/.claude/skills/sales-list
```

## 動作環境

- Python 3 + `playwright` + `openpyxl`
- `python3 -m playwright install chromium`（初回のみ）
