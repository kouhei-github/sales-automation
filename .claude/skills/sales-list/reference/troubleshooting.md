# トラブルシューティング / 手動補完

## 実行環境
```bash
python3 -c "import playwright, openpyxl; print('ok')"     # 依存確認
python3 -m playwright install chromium                    # ブラウザが無い時
```
全スクリプトに `--headed` を付けるとブラウザを表示してデバッグできる (search_gmaps / search_kyujinbox / enrich)。

## 症状別
| 症状 | 原因 / 対処 |
|---|---|
| `結果フィードなし (0件 or ブロック)` | クエリが特殊で 0 件、または Google の自動アクセス検知。`--headed` で確認。検知なら 10〜30 分空ける、`--concurrency 2` に下げる、エリアを変える |
| Google Maps の詳細取得で `detail fail` が多発 | 回線/負荷。`--concurrency 2`。`--resume` で再実行すると取得済みは飛ばす |
| 求人ボックスで `お探しのページが見つかりません` | URL 形式が変わった。トップページで検索して遷移先 URL を確認し、`search_kyujinbox.kb_url` を直す |
| 求人ボックス「Maps解決 0 件」 | Google Maps 側の描画待ち不足 → `search_gmaps.wait_results` のセレクタを確認 (`button[data-item-id="address"]`) |
| HP 巡回で `unreachable` | SSL/タイムアウト/JS 必須サイト。件数が多ければ `--headed` で 1 件開いて確認。空欄のままで良い |
| メール取得率が低い | 多くの企業 HP はフォームのみでメール非掲載。仕様。`お問い合わせページ` 列で代替 |
| 代表者/資本金が空 | 会社概要が画像・PDF、または table/dl 以外の独自マークアップ。手動補完 (下記) |
| Excel を開いたまま export | `PermissionError` → 閉じてから再実行 |
| 同じ会社が別シートに載っている | 旧データが `会社名` ヘッダーの無いシートにある、または社名表記が大きく違う (支店名付き等)。正規化ルールは `common.norm_name` |

## Playwright MCP で手動補完する
スクリプトが取りこぼした会社は、Playwright MCP で同じ抽出ロジックを走らせて埋める。
1. `browser_navigate` で会社概要ページを開く
2. `browser_evaluate` に `scripts/extract_company.js` の中身をそのまま渡す (IIFE なので `() => { return <中身> }` で包む)。`pairs` に key/value が返る
3. 得た値を `enriched.json` の該当社に書き込み、`run.py export` し直す (既に出力済みの行は重複扱いになるので、Excel 側のセルを openpyxl で直接更新する)

## Google Maps のセレクタ (2026-09 時点)
- 結果一覧: `div[role="feed"] a[href*="/maps/place/"]` (aria-label = 店名)。末尾は「リストの最後に到達しました」
- 詳細: `button[data-item-id="address"]` / `button[data-item-id^="phone:tel:"]` / `a[data-item-id="authority"]` (HP) / `button[jsaction*="category"]`
- 1 件ヒットの場合は URL 更新前に詳細パネルが出るので、URL ではなく `address` ボタンの有無で判定している
