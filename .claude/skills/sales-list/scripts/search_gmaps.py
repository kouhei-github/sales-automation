"""Google Maps 検索 → 候補企業 JSON (会社名 / 住所 / 電話 / HP / カテゴリ / 評価)

使い方:
  python3 search_gmaps.py --query "塗装業" --area "東京都" --limit 120 --out candidates.json
複数エリア: --area "新宿区,渋谷区"  (カンマ区切り、順に検索して結合)
"""
import argparse
import asyncio
import re
import urllib.parse

from playwright.async_api import async_playwright

from common import log, new_context, norm_name, save_json, load_json, dedup_keys

FEED = 'div[role="feed"]'
PLACE_LINK = 'a[href*="/maps/place/"]'


async def scroll_feed(page, want):
    """結果フィードを末尾まで or want 件までスクロール"""
    stagnant = 0
    last = 0
    for _ in range(60):
        n = await page.locator(f"{FEED} {PLACE_LINK}").count()
        ended = await page.evaluate(
            '() => { const f=document.querySelector(\'div[role="feed"]\'); return !!f && /リストの最後|最後に到達|reached the end/.test(f.innerText); }')
        if n >= want or ended:
            return n, ended
        await page.evaluate('() => { const f=document.querySelector(\'div[role="feed"]\'); if (f) f.scrollTop = f.scrollHeight; }')
        await page.wait_for_timeout(1300)
        if n == last:
            stagnant += 1
            if stagnant >= 6:
                return n, True
        else:
            stagnant = 0
        last = n
    return last, True


async def list_cards(page):
    return await page.evaluate('''() => [...document.querySelectorAll('div[role="feed"] a[href*="/maps/place/"]')].map(a => {
        const c = a.closest('div[jsaction]') || a.parentElement;
        return { name: a.getAttribute('aria-label') || '', href: a.href, card: (c && c.innerText || '').replace(/\\n/g, ' | ').slice(0, 300) };
    }).filter(x => x.name)''')


DETAIL_JS = '''() => {
  const q = s => document.querySelector(s);
  const lab = e => e ? (e.getAttribute('aria-label') || e.innerText || '').trim() : '';
  const strip = (s, p) => s.replace(p, '').trim();
  const main = q('div[role="main"]');
  const h1s = [...document.querySelectorAll('h1')].map(h => h.innerText.trim()).filter(t => t && t !== '結果');
  const web = q('a[data-item-id="authority"]');
  const cat = q('button[jsaction*="category"]');
  const rating = main && main.querySelector('span[role="img"][aria-label*="つ星"], div[role="img"][aria-label*="つ星"]');
  return {
    name: h1s[0] || (main ? main.getAttribute('aria-label') : '') || '',
    address: strip(lab(q('button[data-item-id="address"]')), /^住所:\\s*/),
    phone: strip(lab(q('button[data-item-id^="phone:tel:"]')), /^電話番号:\\s*/),
    website: web ? web.href : '',
    category: cat ? cat.innerText.trim() : '',
    rating: rating ? rating.getAttribute('aria-label') : '',
    maps_url: location.href,
  };
}'''


async def place_detail(page, href):
    """place URL を直接開いてパネルを読む"""
    try:
        await page.goto(href, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_selector('button[data-item-id="address"], div[role="main"] h1', timeout=12000)
        await page.wait_for_timeout(500)
        return await page.evaluate(DETAIL_JS)
    except Exception as e:  # noqa
        log("  detail fail:", href[:80], type(e).__name__)
        return {}


async def wait_results(page):
    """検索後の状態を待つ: 'feed' (一覧) / 'detail' (1件ヒットで詳細直行) / 'none'"""
    for sel in ('button[aria-label*="同意"]', 'form[action*="consent"] button'):
        if await page.locator(sel).count():
            await page.locator(sel).first.click()
            await page.wait_for_timeout(1500)
    try:
        await page.wait_for_selector('div[role="feed"], button[data-item-id="address"], div[role="main"] h1', timeout=15000)
    except Exception:  # noqa
        return "none"
    await page.wait_for_timeout(1200)
    if await page.locator(FEED).count():
        return "feed"
    if await page.locator('button[data-item-id="address"]').count():
        return "detail"
    return "none"


def gmaps_search_url(q):
    return f"https://www.google.com/maps/search/{urllib.parse.quote(q)}?hl=ja"


async def search_one(ctx, query, area, want):
    page = await ctx.new_page()
    q = f"{query} {area}".strip()
    log(f"Google Maps 検索: {q}")
    await page.goto(gmaps_search_url(q), wait_until="domcontentloaded", timeout=60000)
    mode = await wait_results(page)
    if mode == "detail":
        # 1件だけヒットして詳細パネルに直行した場合
        d = await page.evaluate(DETAIL_JS)
        await page.close()
        return [dict(d, href=d.get("maps_url", ""))] if d.get("name") else []
    if mode != "feed":
        log("  結果フィードなし (0件 or ブロック)。title=", await page.title())
        await page.close()
        return []
    n, ended = await scroll_feed(page, want)
    cards = await list_cards(page)
    log(f"  リスト取得 {len(cards)} 件 (末尾到達={ended})")
    await page.close()
    return cards


async def run(args):
    areas = [a.strip() for a in args.area.split(",") if a.strip()] or [""]
    known = set()
    for p in args.exclude:
        for r in load_json(p, []) or []:
            known |= dedup_keys(r)
    results = load_json(args.out, []) if args.append else []
    seen = {norm_name(r["company"]) for r in results}
    async with async_playwright() as pw:
        browser, ctx = await new_context(pw, headless=not args.headed)
        try:
            for area in areas:
                if len(results) >= args.limit:
                    break
                cards = await search_one(ctx, args.query, area, (args.limit - len(results)) * 2)
                fresh = [c for c in cards if norm_name(c["name"]) not in seen and ("name:" + norm_name(c["name"])) not in known]
                fresh = fresh[: max(0, args.limit - len(results))]
                log(f"  新規候補 {len(fresh)} 件 → 詳細取得")
                sem = asyncio.Semaphore(args.concurrency)
                prog = {"n": 0}

                async def fetch(c):
                    if c.get("address") is not None and c.get("maps_url"):
                        return c
                    async with sem:
                        pg = await ctx.new_page()
                        try:
                            d = await place_detail(pg, c["href"])
                        finally:
                            await pg.close()
                        prog["n"] += 1
                        if prog["n"] % 10 == 0 or prog["n"] == len(fresh):
                            log(f"   詳細 {prog['n']}/{len(fresh)}")
                        d = d or {}
                        d["name"] = c["name"] or d.get("name", "")
                        d["maps_url"] = d.get("maps_url") or c["href"]
                        return d

                details = await asyncio.gather(*[fetch(c) for c in fresh])
                for d in details:
                    if not d.get("name"):
                        continue
                    row = {
                        "company": d["name"], "address": d.get("address", ""), "phone": d.get("phone", ""),
                        "website": d.get("website", ""), "category": d.get("category", ""), "rating": d.get("rating", ""),
                        "maps_url": d.get("maps_url", ""), "source": "Google Maps", "query": f"{args.query} {area}".strip(),
                    }
                    k = norm_name(row["company"])
                    if k in seen:
                        continue
                    seen.add(k)
                    results.append(row)
                    save_json(args.out, results)
                    if len(results) >= args.limit:
                        break
                log(f"  累計 {len(results)} 件")
        finally:
            await browser.close()
    save_json(args.out, results)
    log(f"完了: {len(results)} 件 → {args.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="業種キーワード (例: 塗装業)")
    ap.add_argument("--area", default="", help="エリア。カンマ区切りで複数可")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--out", required=True)
    ap.add_argument("--append", action="store_true", help="--out が既にあれば追記")
    ap.add_argument("--exclude", nargs="*", default=[], help="既知企業 JSON (これに含まれる会社は詳細取得しない)")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--headed", action="store_true")
    asyncio.run(run(ap.parse_args()))
