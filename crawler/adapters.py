# -*- coding: utf-8 -*-
"""プラットフォーム別クローラー。各関数は (title, text, url, ns) を yield する"""
import re
import urllib.parse
import xml.etree.ElementTree as ET

from extract import html_to_text, wikitext_to_text
from fetch import Fetcher, hikamers_get_json


def _safe_title(t):
    return re.sub(r"[\x00-\x1f]", " ", t or "").strip()


# ---------------- MediaWiki API ----------------

def crawl_mw(cfg, fetcher):
    api = cfg["api"]
    site = cfg["site"]
    for ns in cfg.get("namespaces", [0]):
        params = {
            "action": "query", "generator": "allpages", "gapnamespace": ns,
            "gaplimit": "500", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "format": "json", "formatversion": "2",
        }
        cont = None
        while True:
            if cont:
                params["gapcontinue"] = cont
            if cfg.get("pow"):
                data = hikamers_get_json(fetcher, params)
            else:
                fetcher.polite(api)
                r = fetcher.session_for(api).get(api, params=params)
                if r.status_code != 200:
                    raise RuntimeError(f"mw api {api}: HTTP {r.status_code}")
                data = r.json()
            pages = data.get("query", {}).get("pages", [])
            for p in pages:
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
                if len(text) < 20:
                    continue
                url = site + urllib.parse.quote(title)
                yield title, text, url, ns
            # generator + prop=revisions は gapcontinue と rvcontinue の両方が返る → 全部引き継ぐ
            if "continue" in data:
                params.update({k: v for k, v in data["continue"].items()})
            else:
                break


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
