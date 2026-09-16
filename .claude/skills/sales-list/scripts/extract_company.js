// 企業HPの1ページから営業リスト用の生データを抽出する。
// Python (enrich.py) の page.evaluate と、Playwright MCP の browser_evaluate の両方から
// そのまま使える自己完結 IIFE。返り値は JSON 化可能なオブジェクト。
(() => {
  const clean = s => (s || "").replace(/ /g, " ").replace(/[ \t\r\f\v]+/g, " ").replace(/\n\s*\n+/g, "\n").trim();
  const meta = n => { const e = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`); return e ? clean(e.getAttribute("content")) : ""; };
  const pairs = [];
  const push = (k, v) => { k = clean(k).replace(/[:：]\s*$/, ""); v = clean(v); if (k && v && k.length <= 30 && v.length <= 600) pairs.push([k, v]); };

  // 1) table: th/td もしくは 先頭 td をキーとみなす
  document.querySelectorAll("table tr").forEach(tr => {
    const cells = [...tr.children].filter(c => /^(TH|TD)$/.test(c.tagName));
    if (cells.length >= 2) push(cells[0].innerText, cells.slice(1).map(c => c.innerText).join(" "));
  });
  // 2) dl: dt/dd
  document.querySelectorAll("dl").forEach(dl => {
    const kids = [...dl.children]; let k = null;
    kids.forEach(el => { if (el.tagName === "DT") k = el.innerText; else if (el.tagName === "DD" && k) { push(k, el.innerText); k = null; } });
  });
  // 3) "キー：値" 形式の行 (会社概要がテキストのみで書かれているサイト向け)
  const text = clean(document.body ? document.body.innerText : "");
  text.split("\n").forEach(line => {
    const m = line.match(/^([^：:]{1,20})[：:]\s*(.{2,300})$/);
    if (m) push(m[1], m[2]);
  });

  const abs = h => { try { return new URL(h, location.href).href; } catch { return ""; } };
  const links = [];
  const seen = new Set();
  document.querySelectorAll("a[href]").forEach(a => {
    const href = abs(a.getAttribute("href"));
    if (!href || seen.has(href)) return;
    seen.add(href);
    links.push({ text: clean(a.innerText || a.getAttribute("aria-label") || a.title || "").slice(0, 60), href });
  });
  const mailto = links.map(l => l.href).filter(h => /^mailto:/i.test(h)).map(h => decodeURIComponent(h.replace(/^mailto:/i, "").split("?")[0]));
  const tel = links.map(l => l.href).filter(h => /^tel:/i.test(h)).map(h => h.replace(/^tel:/i, ""));

  return {
    url: location.href,
    title: clean(document.title),
    metaDescription: meta("description") || meta("og:description"),
    h1: clean((document.querySelector("h1") || {}).innerText || ""),
    pairs,
    links: links.slice(0, 400),
    mailto,
    tel,
    text: text.slice(0, 8000),
  };
})()
