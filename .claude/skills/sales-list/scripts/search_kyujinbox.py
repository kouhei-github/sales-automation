"""求人ボックス 検索 → 企業名を収集し、Google Maps で住所/電話/HP を解決 → 候補 JSON

使い方:
  python3 search_kyujinbox.py --query "塗装" --area "東京都" --limit 100 --out candidates_kb.json
"""
import argparse
import asyncio
import re
import urllib.parse

from playwright.async_api import async_playwright

from common import log, new_context, norm_name, save_json, load_json, dedup_keys
from search_gmaps import gmaps_search_url, DETAIL_JS, FEED, wait_results

BASE = "https://xn--pckua2a7gp15o89zb.com"  # 求人ボックス.com


def kb_url(query, area, pg):
    path = urllib.parse.quote(f"{query}の仕事" + (f"-{area}" if area else ""))
    return f"{BASE}/{path}" + (f"?pg={pg}" if pg > 1 else "")


async def collect_companies(ctx, query, area, want, max_pages):
    page = await ctx.new_page()
    companies = {}
    for pg in range(1, max_pages + 1):
        url = kb_url(query, area, pg)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        except Exception as e:  # noqa
            log("  kb page fail", pg, type(e).__name__)
            break
        await page.wait_for_timeout(800)
        if await page.locator(".p-result-none-full, .p-result_zero").count() and not await page.locator(".p-result_card--ver1").count():
            log(f"  {pg}ページ目: 結果なし")
            break
        cards = await page.evaluate('''() => [...document.querySelectorAll('.p-result_card--ver1')].map(c => {
            const t = s => { const e = c.querySelector(s); return e ? e.innerText.trim() : ''; };
            const a = c.querySelector('a.p-result_title_link');
            return { company: t('.p-result_companyName'), area: t('.p-result_area').replace(/\\s+/g, ' '), title: t('.p-result_name'),
                     employ: t('.p-result_employType'), link: a ? a.href : '' };
        }).filter(x => x.company)''')
        if not cards:
            log(f"  {pg}ページ目: カードなし → 終了")
            break
        new = 0
        for c in cards:
            k = norm_name(c["company"])
            if not k or k in companies:
                continue
            if re.search(r"非公開|社名非公開|株式会社\s*$", c["company"]):
                continue
            companies[k] = c
            new += 1
        log(f"  {pg}ページ目: {len(cards)} 求人 / 新規企業 {new} / 累計 {len(companies)}")
        if len(companies) >= want:
            break
        if not await page.locator(f'a[href*="pg={pg + 1}"]').count():
            break
    await page.close()
    return list(companies.values())


async def resolve_on_maps(ctx, company, hint):
    """会社名 + エリアで Google Maps を検索し、名前が一致する1件の詳細を返す"""
    page = await ctx.new_page()
    try:
        q = f"{company} {hint}".strip()
        await page.goto(gmaps_search_url(q), wait_until="domcontentloaded", timeout=40000)
        target = norm_name(company)
        mode = await wait_results(page)
        if mode == "detail":
            d = await page.evaluate(DETAIL_JS)
        else:
            if mode != "feed":
                return {}
            cards = await page.evaluate('''() => [...document.querySelectorAll('div[role="feed"] a[href*="/maps/place/"]')].map(a => ({name: a.getAttribute('aria-label')||'', href: a.href}))''')
            hit = next((c for c in cards if c["name"] and (norm_name(c["name"]) in target or target in norm_name(c["name"]))), None)
            if not hit:
                return {}
            await page.goto(hit["href"], wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_selector('button[data-item-id="address"], div[role="main"] h1', timeout=12000)
            await page.wait_for_timeout(400)
            d = await page.evaluate(DETAIL_JS)
        n = norm_name(d.get("name", ""))
        if not n or not (n in target or target in n):
            return {}
        return d
    except Exception as e:  # noqa
        log("  maps resolve fail:", company, type(e).__name__)
        return {}
    finally:
        await page.close()


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
                log(f"求人ボックス 検索: {args.query} / {area}")
                comps = await collect_companies(ctx, args.query, area, (args.limit - len(results)) * 2, args.max_pages)
                fresh = [c for c in comps if norm_name(c["company"]) not in seen and ("name:" + norm_name(c["company"])) not in known]
                log(f"  新規企業 {len(fresh)} 件 → Google Maps で所在地/HP を解決")
                sem = asyncio.Semaphore(args.concurrency)
                prog = {"n": 0, "hit": 0}

                async def one(c):
                    async with sem:
                        # 勤務地の市区町村 (駅名は除く) をヒントに
                        hint = " ".join(c["area"].split(" ")[:2]) if c.get("area") else area
                        d = await resolve_on_maps(ctx, c["company"], hint)
                        prog["n"] += 1; prog["hit"] += bool(d)
                        if prog["n"] % 10 == 0:
                            log(f"   Maps解決 {prog['n']} 社処理 / {prog['hit']} 社一致")
                        return c, d

                need = args.limit - len(results)
                pairs = []
                for i in range(0, len(fresh), max(need, 1)):
                    if len(results) + len(pairs) >= args.limit:
                        break
                    pairs += await asyncio.gather(*[one(c) for c in fresh[i:i + need]])
                for c, d in pairs:
                    k = norm_name(c["company"])
                    if k in seen or len(results) >= args.limit:
                        continue
                    seen.add(k)
                    results.append({
                        "company": c["company"], "address": d.get("address", ""), "phone": d.get("phone", ""),
                        "website": d.get("website", ""), "category": d.get("category", ""), "rating": d.get("rating", ""),
                        "maps_url": d.get("maps_url", ""), "source": "求人ボックス", "query": f"{args.query} {area}".strip(),
                        "kb_area": c.get("area", ""), "kb_job_title": c.get("title", ""), "kb_link": c.get("link", ""),
                    })
                    save_json(args.out, results)
                log(f"  累計 {len(results)} 件 (Maps解決 {sum(1 for r in results if r['maps_url'])} 件)")
        finally:
            await browser.close()
    save_json(args.out, results)
    log(f"完了: {len(results)} 件 → {args.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="職種/業種キーワード (例: 塗装)")
    ap.add_argument("--area", default="", help="エリア。カンマ区切りで複数可")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=15)
    ap.add_argument("--out", required=True)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--headed", action="store_true")
    asyncio.run(run(ap.parse_args()))
