# -*- coding: utf-8 -*-
"""プラットフォーム別クローラー。各関数は (title, text, url, ns) を yield する"""
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from extract import html_to_text, wikitext_to_text
from fetch import Fetcher, hikamers_get_json


def _safe_title(t):
    return re.sub(r"[\x00-\x1f]", " ", t or "").strip()


# ---------------- MediaWiki API ----------------

def _mw_get(fetcher, cfg, params):
    api = cfg["api"]
    for attempt in range(5):
        if cfg.get("pow"):
            data = hikamers_get_json(fetcher, params)
            return data
        fetcher.polite(api)
        r = fetcher.session_for(api).get(api, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (403, 429) and attempt < 4:
            time.sleep(2 ** attempt + 2)
            continue
        raise RuntimeError(f"mw api {api}: HTTP {r.status_code}")
    raise RuntimeError(f"mw api {api}: retries exhausted")


def _mw_namespaces(fetcher, cfg):
    """siteinfo から全名前空間を取得 (8=MediaWiki システムメッセージ と 9 以外)"""
    cache = getattr(_mw_namespaces, "_cache", {})
    key = cfg["key"]
    if key not in cache:
        data = _mw_get(fetcher, cfg, {"action": "query", "meta": "siteinfo", "siprop": "namespaces",
                                      "format": "json", "formatversion": "2"})
        ns = data["query"]["namespaces"]
        lst = sorted(int(k) for k in ns.keys() if int(k) >= 0 and int(k) not in (8, 9))
        cache[key] = lst
    return cache[key]


def crawl_mw(cfg, fetcher):
    """2段階: list=allpages でタイトル一覧 → titles=20件ずつ revisions 取得。
    ※ 一部WikiのWAFは generator=allpages を403でブロックするが list=allpages は通る"""
    api = cfg["api"]
    site = cfg["site"]
    for ns in _mw_namespaces(fetcher, cfg):
        titles = []
        params = {
            "action": "query", "list": "allpages", "apnamespace": ns,
            "aplimit": "500", "format": "json", "formatversion": "2",
        }
        while True:
            data = _mw_get(fetcher, cfg, params)
            for p in data.get("query", {}).get("allpages", []):
                t = _safe_title(p.get("title", ""))
                if t and "|" not in t:
                    titles.append(t)
            if "continue" in data:
                params.update({k: v for k, v in data["continue"].items()})
            else:
                break
        for i in range(0, len(titles), 20):
            batch = titles[i:i + 20]
            data = _mw_get(fetcher, cfg, {
                "action": "query", "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "format": "json", "formatversion": "2",
                "titles": "|".join(batch),
            })
            for p in data.get("query", {}).get("pages", []):
                title = _safe_title(p.get("title", ""))
                if not title:
                    continue
                revs = p.get("revisions") or []
                content = ""
                if revs:
                    slots = revs[0].get("slots") or {}
                    content = (slots.get("main") or {}).get("content", "")
                    if not content:
                        content = revs[0].get("*", "")
                if not content or not content.strip():
                    continue
                text = wikitext_to_text(content)
                if ns == 6:
                    # ファイルページ: 説明が無くてもファイル名自体を検索可能にする
                    if len(text) < 20:
                        text = title
                elif len(text) < 20:
                    continue
                url = site + urllib.parse.quote(title)
                yield title, text, url, ns


# ---------------- atwiki ----------------

def crawl_atwiki(cfg, fetcher):
    site = cfg["site"]
    host = urllib.parse.urlparse(site).netloc  # w.atwiki.jp
    wiki = urllib.parse.urlparse(site).path.strip("/").split("/")[0]
    list_html = fetcher.get_text(site.rstrip("/") + "/list")
    # <a href="//w.atwiki.jp/{wiki}/pages/NN.html" title="X (Nd)"> ... </a>
    pages = {}
    for m in re.finditer(r'<a[^>]+href="(//%s/%s/pages/(\d+)\.html)"[^>]*>(.*?)</a>'
                         % (re.escape(host), re.escape(wiki)), list_html, re.S):
        url, pid, inner = m.groups()
        tm = re.search(r'title="([^"]*)"', m.group(0))
        name = ""
        if tm:
            name = re.sub(r"\s*\(\d+d\)$", "", tm.group(1)).strip()
        if not name:
            name = re.sub(r"<[^>]+>", "", inner).strip()
        pages[pid] = (name, "https:" + url)
    if not pages:
        # 別形式 (href が https:// 直書きの場合)
        for m in re.finditer(r'<a[^>]+href="(https?://%s/%s/pages/(\d+)\.html)"[^>]*>(.*?)</a>'
                             % (re.escape(host), re.escape(wiki)), list_html, re.S):
            url, pid, inner = m.groups()
            tm = re.search(r'title="([^"]*)"', m.group(0))
            name = re.sub(r"\s*\(\d+d\)$", "", tm.group(1)).strip() if tm else re.sub(r"<[^>]+>", "", inner).strip()
            pages[pid] = (name, url)
    for pid, (name, url) in sorted(pages.items(), key=lambda x: int(x[0])):
        html = fetcher.get_text(url, referer=site.rstrip("/") + "/list")
        text = html_to_text(html, container=[("div", "id", "wikibody")])
        if not text:
            text = html_to_text(html)
        title = name or _safe_title(re.sub(r"\s*-\s*.*$", "", re.search(r"<title>([^<]*)</title>", html).group(1) if re.search(r"<title>([^<]*)</title>", html) else ""))
        if len(text) >= 20:
            yield title, text, url, 0


# ---------------- seesaa / memo.wiki (sitemap + /d/) ----------------

def _sitemap_urls(fetcher, site):
    xml = fetcher.get_text(site.rstrip("/") + "/sitemap.xml")
    urls = re.findall(r"<loc>(.*?)</loc>", xml, re.S)
    return [u.strip() for u in urls]


def crawl_seesaa(cfg, fetcher):
    site = cfg["site"]
    for url in _sitemap_urls(fetcher, site):
        if not url.startswith(site):
            continue
        html = fetcher.get_text(url, enc="euc-jp")
        text = html_to_text(html, container=[("div", "id", "page-body-inner")])
        if not text:
            text = html_to_text(html, container=[("div", "id", "main")])
        m = re.search(r"<title>([^<]*)</title>", html)
        title = _safe_title(m.group(1)) if m else urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
        title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
        if len(text) >= 20:
            yield title, text, url, 0


def crawl_memo(cfg, fetcher):
    site = cfg["site"]
    for url in _sitemap_urls(fetcher, site):
        if not url.startswith(site):
            continue
        html = fetcher.get_text(url, enc="euc-jp")
        text = html_to_text(html, container=[("div", "class", "wiki-section-body-1")])
        if not text:
            text = html_to_text(html)
        m = re.search(r"<title>([^<]*)</title>", html)
        title = _safe_title(m.group(1)) if m else urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
        title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
        if len(text) >= 20:
            yield title, text, url, 0


# ---------------- fc2 ----------------

def crawl_fc2(cfg, fetcher):
    site = cfg["site"]
    for url in _sitemap_urls(fetcher, site):
        if not url.startswith(site):
            continue
        html = fetcher.get_text(url)
        text = html_to_text(html, container=[("div", "class", "user_body")])
        if not text:
            text = html_to_text(html, container=[("div", "id", "main")])
        m = re.search(r"<title>([^<]*)</title>", html)
        title = _safe_title(m.group(1)) if m else urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
        title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
        if len(text) >= 20:
            yield title, text, url, 0


# ---------------- wikiwiki (FSWiki系) ----------------

SYSTEM_PAGES = re.compile(
    r"(/Help$|/MenuBar$|/SideMenu$|/RecentChanges$|/RecentCreated$|/SandBox$|/InterWiki|"
    r"/BracketName$|/Glossary$|/FrontPage$|/Popular100$|/Today100$|/整形ルール$|/ヘルプ$)", re.I)


def crawl_wikiwiki(cfg, fetcher):
    site = cfg["site"]
    wiki = urllib.parse.urlparse(site).path.strip("/").split("/")[0]
    seen = set()
    queue = []
    for cmd in ("::cmd/list", "RecentCreated"):
        try:
            html = fetcher.get_text(site.rstrip("/") + "/" + cmd)
        except RuntimeError:
            continue
        for m in re.finditer(r'href="(/%s/([^"?#]+))"' % re.escape(wiki), html):
            path, name = m.groups()
            if "::" in name or "?" in name:
                continue
            if SYSTEM_PAGES.search(path):
                continue
            page = urllib.parse.unquote(name)
            if page not in seen:
                seen.add(page)
                queue.append(page)
    # フロントページからも拾う
    html = fetcher.get_text(site)
    for m in re.finditer(r'href="(/%s/([^"?#]+))"' % re.escape(wiki), html):
        path, name = m.groups()
        if "::" in name or "?" in name or SYSTEM_PAGES.search(path):
            continue
        page = urllib.parse.unquote(name)
        if page not in seen:
            seen.add(page)
            queue.append(page)
    for page in sorted(queue):
        url = site + urllib.parse.quote(page)
        try:
            html = fetcher.get_text(url)
        except RuntimeError:
            continue
        text = html_to_text(html, container=[("div", "id", "content")])
        if not text:
            text = html_to_text(html, container=[("div", "id", "body")])
        title = page
        m = re.search(r"<title>([^<]*)</title>", html)
        if m:
            t = m.group(1).split(" - ")[0].strip()
            if t and t != "404":
                title = t
        if len(text) >= 20:
            yield title, text, url, 0


# ---------------- wiki3.jp ----------------

def crawl_wiki3(cfg, fetcher):
    site = cfg["site"]
    wiki = urllib.parse.urlparse(site).path.strip("/").split("/")[0]
    seen = set()
    queue = []
    for src in (site.rstrip("/") + "/pageList", site.rstrip("/") + "/"):
        html = fetcher.get_text(src)
        for m in re.finditer(r'href="/(%s/name/([^"?#]+))"' % re.escape(wiki), html):
            path, enc = m.groups()
            page = urllib.parse.unquote(enc)
            if page not in seen:
                seen.add(page)
                queue.append(("name", page))
        for m in re.finditer(r'href="/(%s/page/(\d+))"' % re.escape(wiki), html):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                queue.append(("page", m.group(2)))
    for kind, page in sorted(queue):
        if kind == "name":
            url = site.rstrip("/") + "/name/" + urllib.parse.quote(page)
        else:
            url = site.rstrip("/") + "/page/" + page
        html = fetcher.get_text(url)
        text = html_to_text(html, container=[("div", "class", "main_content")])
        if not text:
            text = html_to_text(html, container=[("div", "id", "main")])
        title = page.rsplit("/", 1)[-1]
        m = re.search(r"<title>([^<]*)</title>", html)
        if m:
            t = m.group(1).strip()
            if t and "wiki3.jp" not in t:
                title = re.sub(r"\s*[|｜-].*$", "", t)
        if len(text) >= 20:
            yield title, text, url, 0


def crawl_810ch(cfg, fetcher):
    """810ちゃんねる (および read.cgi 形式のオニオン掲示板): 板トップ → スレ一覧 → 全レス。スレ=1ページ(全レス連結)"""
    board = cfg["site"].rstrip("/")
    bname = board.rsplit("/", 1)[-1]
    read_url = cfg.get("read_url", "").rstrip("/")
    html = fetcher.get_text(board)
    tids = sorted(set(re.findall(r"/" + re.escape(bname) + r"/(\d+)", html)))
    if not tids:
        print(f"  810ch {bname}: no threads")
        return
    for tid in tids:
        url = f"{read_url}/{tid}/" if read_url else f"{board}/{tid}"
        try:
            th = fetcher.get_text(url)
        except Exception:
            continue
        m = re.search(r"<title>(.*?)</title>", th, re.DOTALL)
        title = m.group(1).strip() if m else f"スレ{tid}"
        title = re.sub(r"\s*-\s*[^-]*掲示板[^-]*-\s*810ちゃんねる\s*$", "", title).strip()
        blocks = re.split(r'<div\s+id="(\d+)"\s+class="post"[^>]*>', th)
        parts = []
        for k in range(1, len(blocks) - 1, 2):
            num = blocks[k]
            ph = blocks[k + 1]
            nm = re.search(r'<span class="name"[^>]*>(.*?)</span>', ph, re.DOTALL)
            dm = re.search(r'<span class="dateid"[^>]*>(.*?)</span>', ph, re.DOTALL)
            mm = re.search(r'<div class="message"[^>]*>(.*?)</div>', ph, re.DOTALL)
            name = html_to_text(nm.group(1)) if nm else ""
            date = html_to_text(dm.group(1)) if dm else ""
            body = html_to_text(mm.group(1)) if mm else ""
            if body:
                parts.append(f"{num} {name} {date}\n{body}".strip())
        text = "\n\n".join(parts)
        if len(text) >= 20:
            yield title, text, url, 0


def crawl_nicodic(cfg, fetcher):
    """ニコニコ大百科: 記事本文 + 記事掲示板(全ページ、30レス刻み)"""
    art_url = cfg["site"]
    board = cfg["board"]
    ah = fetcher.get_text(art_url)
    tm = re.search(r"<title>(.*?)</title>", ah, re.DOTALL)
    art_title = tm.group(1).strip() if tm else "記事"
    art_title = re.sub(r"\s*-\s*ニコニコ大百科\s*$", "", art_title).strip()
    art_title = re.sub(r"\s*\[単語記事\]\s*$", "", art_title).strip()
    # 記事本文
    i = ah.find('<div class="article" id="article">')
    if i > 0:
        start = ah.find("<p", i)
        if start < 0:
            start = ah.find("<h2", i)
        end = ah.find("a-bottomMenu", i)
        if end < 0:
            end = min(len(ah), i + 40000)
        if start > 0 and end > start:
            body = html_to_text(ah[start:end])
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            if len(body) >= 20:
                yield f"{art_title} (記事)", body, art_url, 0
    # 掲示板
    board = cfg["board"].rstrip("/")
    bh = fetcher.get_text(board + "/1-")
    last_start = 1
    for m in re.finditer(r"/b/a/[^\"']*?/(\d+)-", bh):
        last_start = max(last_start, int(m.group(1)))
    res_parts = []
    for sn in range(1, last_start + 1, 30):
        ph = fetcher.get_text(board + f"/{sn}-")
        if "st-bbs_reshead" not in ph:
            continue
        blocks = re.split(r'<dt class="st-bbs_reshead"[^>]*data-res_no="(\d+)"[^>]*>', ph)
        for k in range(1, len(blocks) - 1, 2):
            res_no = blocks[k]
            rb = blocks[k + 1]
            body = ""
            dd = rb.find('<dd class="st-bbs_resbody"')
            if dd >= 0:
                bm = re.search(r'<div class="bbs_resbody_inner"[^>]*>(.*?)</div>', rb[dd:], re.DOTALL)
                if bm:
                    body = html_to_text(bm.group(1))
            nm = re.search(r'<span class="st-bbs_name bbs_name"[^>]*>(.*?)</span>', rb, re.DOTALL)
            ts = re.search(r'<span class="bbs_resInfo_resTime"[^>]*>(.*?)</span>', rb, re.DOTALL)
            name = html_to_text(nm.group(1)) if nm else ""
            tsv = html_to_text(ts.group(1)) if ts else ""
            if body:
                res_parts.append(f"{res_no} {name} {tsv}\n{body}")
    if res_parts:
        yield f"{art_title} (掲示板)", "\n\n".join(res_parts), board, 0
