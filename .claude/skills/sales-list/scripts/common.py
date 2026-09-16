"""共通ユーティリティ: ブラウザ生成 / 正規化 / 重複キー / ログ"""
import asyncio
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

SKILL_DIR = Path(__file__).resolve().parent.parent
EXTRACT_JS = (SKILL_DIR / "scripts" / "extract_company.js").read_text(encoding="utf-8")

BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}


def log(*a):
    print(datetime.now().strftime("[%H:%M:%S]"), *a, file=sys.stderr, flush=True)


async def new_context(pw, headless=True, block_assets=True):
    browser = await pw.chromium.launch(headless=headless, args=["--lang=ja-JP", "--disable-blink-features=AutomationControlled"])
    ctx = await browser.new_context(
        locale="ja-JP", timezone_id="Asia/Tokyo", user_agent=UA,
        viewport={"width": 1400, "height": 900}, ignore_https_errors=True,
    )
    if block_assets:
        async def _route(route):
            if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                await route.abort()
            else:
                await route.continue_()
        await ctx.route("**/*", _route)
    ctx.set_default_timeout(25000)
    return browser, ctx


# ---------- 正規化 ----------
_CORP = r"(株式会社|有限会社|合同会社|合資会社|合名会社|一般社団法人|一般財団法人|医療法人|社会福祉法人|学校法人|特定非営利活動法人|NPO法人|\(株\)|\(有\)|㈱|㈲|株|有)"


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def norm_name(name):
    """会社名の重複判定キー: 法人格・空白・記号を除去し小文字化"""
    s = nfkc(name).lower()
    s = re.sub(_CORP, "", s)
    s = re.sub(r"[\s　・,，.。、()（）「」『』\-‐－―_/／|｜]", "", s)
    return s


def norm_domain(url):
    if not url:
        return ""
    u = nfkc(url).lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0].split("?")[0].split("#")[0]


def norm_phone(p):
    d = re.sub(r"\D", "", nfkc(p))
    return d if 9 <= len(d) <= 11 else ""


def dedup_keys(row):
    """1社から得られる重複判定キー群 (どれか1つでも既存と一致すれば重複)"""
    keys = set()
    n = norm_name(row.get("company") or row.get("会社名") or "")
    if n:
        keys.add("name:" + n)
    d = norm_domain(row.get("website") or row.get("HP URL") or "")
    if d and not is_generic_domain(d):
        keys.add("dom:" + d)
    ph = norm_phone(row.get("phone") or row.get("電話番号") or "")
    if ph:
        keys.add("tel:" + ph)
    return keys


GENERIC_DOMAINS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "ameblo.jp",
    "wix.com", "wixsite.com", "jimdo.com", "jimdofree.com", "goo.gl", "google.com", "line.me",
    "tabelog.com", "hotpepper.jp", "ekiten.jp", "indeed.com", "en-gage.net", "linkedin.com",
    "note.com", "peraichi.com", "studio.site", "base.shop", "shop-pro.jp", "stores.jp",
    "goo-net.com", "carsensor.net", "mapion.co.jp", "navitime.co.jp", "itp.ne.jp", "rakuten.co.jp", "amazon.co.jp",
    "houzz.jp", "nuri-kae.jp", "reform-guide.jp", "suumo.jp", "homes.co.jp", "athome.co.jp", "baitoru.com", "townwork.net",
)


def is_generic_domain(d):
    return any(d == g or d.endswith("." + g) for g in GENERIC_DOMAINS)


def safe_sheet_name(name):
    s = re.sub(r"[\[\]:*?/\\]", "_", nfkc(name))
    return (s or "営業リスト")[:31]


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def today():
    return datetime.now().strftime("%Y-%m-%d")
