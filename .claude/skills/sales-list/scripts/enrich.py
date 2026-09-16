"""候補企業の HP を巡回し、営業リスト項目を抽出する。

入力 JSON (search_*.py の出力) の各 row に以下を追加:
  email, contact_url, company_page_url, representative, hq_address, branches, capital,
  established, employees, business_raw, meta_description, hp_title, about_text, description(暫定)
HP が無い / 到達不能なら空欄のまま。

使い方: python3 enrich.py --in candidates.json --out enriched.json [--concurrency 4]
"""
import argparse
import asyncio
import re
import urllib.parse

from playwright.async_api import async_playwright

from common import EXTRACT_JS, log, new_context, load_json, save_json, nfkc, norm_domain, is_generic_domain

COMPANY_LINK = re.compile(r"会社概要|会社案内|企業情報|会社情報|企業概要|企業案内|会社紹介|法人概要|事業所概要|about|company|corporate|profile|outline|overview", re.I)
CONTACT_LINK = re.compile(r"お問い?合わ?せ|お問合せ|問合せ|ご相談|contact|inquiry|toiawase", re.I)
SKIP_LINK = re.compile(r"\.(pdf|jpg|jpeg|png|gif|zip|doc|xls|ppt)x?($|\?)|mailto:|tel:|javascript:|#$|/wp-json|/feed|login|recruit|採用|求人|privacy|プライバシー|sitemap", re.I)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s?(?:@|＠|\[at\]|\(at\)|【at】)\s?[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(0\d{1,4})[-‐－ー―(（ ]?(\d{1,4})[-‐－ー―)） ]?(\d{3,4})(?!\d)")
BAD_EMAIL = re.compile(r"example|sample|test@|hoge|xxx|dummy|sentry|wixpress|\.png|\.jpg|\.gif|\.svg|\.webp|\.js$|@\d|noreply|no-reply|yourname|your-?mail", re.I)

KEYS = {
    "representative": re.compile(r"^(代表者|代表取締役(社長|会長|CEO)?|代表(社員|理事|税理士|弁護士|司法書士|行政書士|社労士|社会保険労務士|公認会計士|所長|パートナー|医師)?|所長|社長|取締役社長|理事長|院長|園長|店主|事務所代表|CEO)(名|氏名)?$"),
    "capital": re.compile(r"資本金"),
    "established": re.compile(r"^(設立|創業|設立年月日|創立|設立年月|創業年)"),
    "employees": re.compile(r"従業員|社員数|職員数|スタッフ数"),
    "hq_address": re.compile(r"^(本社|本社所在地|所在地|住所|本店|本店所在地|本社住所|会社所在地|本部|本社・工場|本社／工場)$"),
    "branches": re.compile(r"支店|支社|営業所|拠点|事業所|工場|子会社|グループ会社|関連会社|関係会社|店舗|ショールーム|センター"),
    "business_raw": re.compile(r"^(事業内容|業務内容|主な事業|事業概要|営業品目|業種|主要業務|事業|取扱品目|サービス内容|業務)$"),
    "phone_kv": re.compile(r"^(TEL|Tel|tel|電話|電話番号|お電話|代表電話|TEL/FAX|TEL・FAX)$"),
    "email_kv": re.compile(r"^(E-?mail|Mail|メール|メールアドレス|e-mail)$", re.I),
}


def clean_val(v, limit=300):
    v = nfkc(v).replace("\n", " ")
    v = re.sub(r"\s+", " ", v)
    return v[:limit]


def pick_emails(data):
    found = []
    for m in data.get("mailto", []):
        found.append(m)
    for m in EMAIL_RE.findall(data.get("text", "")):
        found.append(m)
    for k, v in data.get("pairs", []):
        if KEYS["email_kv"].search(k):
            found += EMAIL_RE.findall(v)
    out = []
    for e in found:
        e = re.sub(r"\s?(?:＠|\[at\]|\(at\)|【at】)\s?", "@", nfkc(e)).strip().lower()
        if BAD_EMAIL.search(e) or e in out or "@" not in e:
            continue
        out.append(e)
    return out


def pick_phone(data):
    for t in data.get("tel", []):
        d = re.sub(r"\D", "", nfkc(t))
        if 10 <= len(d) <= 11 and d.startswith("0"):
            return f"{d[:-8]}-{d[-8:-4]}-{d[-4:]}" if len(d) == 10 else f"{d[:3]}-{d[3:7]}-{d[7:]}"
    for k, v in data.get("pairs", []):
        if KEYS["phone_kv"].search(k):
            m = PHONE_RE.search(nfkc(v))
            if m:
                return "-".join(m.groups())
    m = re.search(r"(?:TEL|Tel|tel|電話)[^\d]{0,6}" + PHONE_RE.pattern, nfkc(data.get("text", "")))
    if m:
        return "-".join(m.groups()[-3:])
    return ""


def pick_by_key(data, key, limit=300, multi=False):
    vals = []
    for k, v in data.get("pairs", []):
        k2 = nfkc(k).replace(" ", "")
        if KEYS[key].search(k2):
            v2 = clean_val(v, limit)
            if v2 and v2 not in vals:
                vals.append(k2 + "：" + v2 if multi else v2)
                if not multi:
                    break
    return " / ".join(vals)[:limit * 3] if multi else (vals[0] if vals else "")


def clean_representative(v):
    v = re.sub(r"^((代表取締役|代表社員|代表理事|取締役|代表)?(社長|会長|税理士|弁護士|司法書士|行政書士|社労士|社会保険労務士|公認会計士|所長|パートナー)?|代表者|代表|理事長|院長)\s*[:：]?\s*", "", v)
    v = re.sub(r"^(税理士|公認会計士|弁護士|司法書士|行政書士|社労士)\s*", "", v)
    v = re.sub(r"\s*(CEO|C\.E\.O\.|兼.*)$", "", v)
    return v.strip()[:40]


PREF = "北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県"
ADDR_LIKE = re.compile(r"〒|(" + PREF + r")|[市区町村郡]")
TELFAX = re.compile(r"\s*(TEL|Tel|tel|電話|FAX|Fax|fax)[:：]?\s*[\d\-‐－()（）]+")


PREF_START = re.compile(r"^(?:" + PREF + r")")


def split_addresses(v):
    """『本社 〒... 支店 〒...』のように複数住所が1セルにある場合に分割する。
    住所の開始 = 〒 トークン (〒が無ければ都道府県で始まるトークン)。
    直前の短いラベル (本社 / 川崎南店 / 水戸工場) はその住所の先頭に付け替える。"""
    v = TELFAX.sub("", v).strip()
    tokens = v.split()
    use_pref = "〒" not in v
    starts = [i for i, t in enumerate(tokens) if (t.startswith("〒") if not use_pref else PREF_START.match(t))]
    if len(starts) == 0 or (use_pref and len(starts) < 2):
        return [v]
    segs = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(tokens)
        body = tokens[i:end]
        # 次の住所のラベルになる末尾トークンを切り離す
        if n + 1 < len(starts) and len(body) > 1 and not re.search(r"\d", body[-1]) and len(body[-1]) <= 12 and not ADDR_LIKE.search(body[-1]):
            body = body[:-1]
        label = ""
        j = i - 1
        if j >= 0 and j >= (starts[n - 1] if n else 0):
            prev = tokens[j]
            if not re.search(r"\d", prev) and len(prev) <= 12 and not ADDR_LIKE.search(prev) and (n == 0 or j > starts[n - 1]):
                label = prev
        segs.append((label + " " + " ".join(body)).strip())
    return segs or [v]


def clean_branches(pairs_text):
    out = []
    for seg in pairs_text.split(" / "):
        k, _, v = seg.partition("：")
        if re.search(r"認証|許可|登録|番号|免許", k) or not ADDR_LIKE.search(v):
            continue
        out.append(seg)
    return " / ".join(out)


JP_NAME = r"[一-龥々〆ヶ]{1,4}[\s\u3000]?[一-龥々ぁ-んァ-ヶー]{1,6}"
REP_LINE = re.compile(r"^(?:代表者?|所長|代表(?:税理士|社員|取締役|理事|弁護士|司法書士|行政書士|社労士|公認会計士|所長)|院長|理事長|社長)[\s\u3000:：]+(" + JP_NAME + r")(?:\s*[（(].{0,20}[)）])?\s*$")
NAME_OFFICE = re.compile(r"^(" + JP_NAME + r"?)\s*(税理士|公認会計士|司法書士|行政書士|社会保険労務士|社労士|弁護士|会計|土地家屋調査士|弁理士|不動産鑑定士)(法人|事務所)")


def representative_from_text(text):
    """『代表 山田太郎』『所長 山田 太郎』のように行単位で書かれた代表者名"""
    for line in text.split("\n"):
        m = REP_LINE.match(line.strip())
        if m:
            return m.group(1).strip()
    return ""


def representative_from_company(company):
    """『山田太郎税理士事務所』のような個人名事務所は名称から代表者を取る"""
    m = NAME_OFFICE.match(nfkc(company))
    if not (m and m.group(1) and m.group(3) == "事務所"):
        return ""
    name = m.group(1).strip()
    core = name.replace(" ", "").replace("\u3000", "")
    if not (3 <= len(core) <= 6) or re.search(r"法人|税務|会計|事務|総合|経営|センター|オフィス|パートナー", name):
        return ""
    if not re.search(r"[一-龥々]", core) or re.fullmatch(r"[ァ-ヶー]+", core):
        return ""
    return name + "（事務所名より推定）"


def first_paragraph(text):
    for line in text.split("\n"):
        line = line.strip()
        if 40 <= len(line) <= 400 and not re.search(r"cookie|クッキー|javascript|©|copyright|all rights|^(住所|〒|TEL|電話|営業時間|受付)", line, re.I):
            return line
    return ""


async def fetch(page, url):
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(700)
        if resp and resp.status >= 400:
            return None
        return await page.evaluate(EXTRACT_JS)
    except Exception as e:  # noqa
        log("   fetch fail:", url[:80], type(e).__name__)
        return None


def internal(links, base):
    bd = norm_domain(base)
    return [l for l in links if norm_domain(l["href"]) == bd and not SKIP_LINK.search(l["href"])]


def score_links(links, pat):
    scored = []
    for l in links:
        s = 0
        if pat.search(l["text"]):
            s += 2
        if pat.search(urllib.parse.unquote(l["href"])):
            s += 1
        if s:
            scored.append((s, len(l["href"]), l["href"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for _, _, h in scored:
        if h not in out:
            out.append(h)
    return out


async def enrich_one(ctx, row):
    site = row.get("website", "")
    if not site or is_generic_domain(norm_domain(site)):
        row.setdefault("hp_status", "no_website" if not site else "generic_site")
        row["representative"] = row.get("representative") or representative_from_company(row.get("company", ""))
        return row
    page = await ctx.new_page()
    try:
        top = await fetch(page, site)
        if not top:
            row["hp_status"] = "unreachable"
            return row
        row["hp_status"] = "ok"
        row["website"] = top["url"] if top["url"].startswith("http") else site
        row["hp_title"] = top["title"]
        row["meta_description"] = top["metaDescription"]
        links = internal(top["links"], row["website"])
        company_urls = score_links(links, COMPANY_LINK)[:2]
        contact_urls = score_links(links, CONTACT_LINK)[:1]
        row["company_page_url"] = company_urls[0] if company_urls else ""
        row["contact_url"] = contact_urls[0] if contact_urls else ""
        pages = [top]
        for u in company_urls + contact_urls:
            d = await fetch(page, u)
            if d:
                pages.append(d)
        merged = {"pairs": [], "mailto": [], "tel": [], "text": ""}
        for d in pages:
            merged["pairs"] += d["pairs"]
            merged["mailto"] += d["mailto"]
            merged["tel"] += d["tel"]
            merged["text"] += "\n" + d["text"]
        emails = pick_emails(merged)
        row["email"] = emails[0] if emails else ""
        row["email_all"] = ", ".join(emails[:3])
        row["representative"] = (clean_representative(pick_by_key(merged, "representative", 60))
                                 or representative_from_text(merged["text"])
                                 or representative_from_company(row.get("company", "")))
        row["capital"] = pick_by_key(merged, "capital", 60)
        row["established"] = pick_by_key(merged, "established", 40)
        row["employees"] = pick_by_key(merged, "employees", 40)
        hq = pick_by_key(merged, "hq_address", 400)
        extra = ""
        if hq:
            parts = split_addresses(hq)
            hq = parts[0][:150] if parts else hq[:150]
            extra = " / ".join(parts[1:])[:300]
        row["hq_address"] = hq or row.get("address", "")
        branches = clean_branches(pick_by_key(merged, "branches", 200, multi=True))
        row["branches"] = " / ".join(x for x in (extra, branches) if x)[:600]
        row["business_raw"] = pick_by_key(merged, "business_raw", 400)
        if not row.get("phone"):
            row["phone"] = pick_phone(merged)
        about = pages[1]["text"] if len(pages) > 1 else ""
        row["about_text"] = (about or top["text"])[:1500]
        row["description"] = (row["meta_description"] if len(row["meta_description"]) >= 20 else "") or row["business_raw"] or first_paragraph(top["text"])
        return row
    finally:
        await page.close()


async def run(args):
    rows = load_json(args.inp, [])
    out = load_json(args.out, []) if args.resume else []
    done = {r.get("company") for r in out}
    todo = [r for r in rows if r.get("company") not in done]
    log(f"HP巡回: {len(todo)} 社 (済 {len(done)})")
    sem = asyncio.Semaphore(args.concurrency)
    async with async_playwright() as pw:
        browser, ctx = await new_context(pw, headless=not args.headed)
        try:
            async def one(i, r):
                async with sem:
                    log(f" [{i + 1}/{len(todo)}] {r.get('company')}  {r.get('website') or '(HPなし)'}")
                    try:
                        return await asyncio.wait_for(enrich_one(ctx, dict(r)), timeout=150)
                    except Exception as e:  # noqa
                        log("   enrich fail:", r.get("company"), type(e).__name__)
                        r = dict(r); r["hp_status"] = "error"; return r
            for i in range(0, len(todo), args.concurrency * 2):
                batch = todo[i:i + args.concurrency * 2]
                res = await asyncio.gather(*[one(i + j, r) for j, r in enumerate(batch)])
                out += res
                save_json(args.out, out)
        finally:
            await browser.close()
    save_json(args.out, out)
    ok = sum(1 for r in out if r.get("hp_status") == "ok")
    log(f"完了: {len(out)} 社 / HP到達 {ok} / メール {sum(1 for r in out if r.get('email'))} / 代表者 {sum(1 for r in out if r.get('representative'))} / 資本金 {sum(1 for r in out if r.get('capital'))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--headed", action="store_true")
    asyncio.run(run(ap.parse_args()))
