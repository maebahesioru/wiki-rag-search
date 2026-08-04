# -*- coding: utf-8 -*-
"""HTML / wikitext → テキスト変換 & チャンキング"""
import html as html_lib
import re
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "br",
              "table", "ul", "ol", "dl", "blockquote", "section", "article", "dt", "dd", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0
        self.in_script_style = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.in_script_style += 1
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.in_script_style = max(0, self.in_script_style - 1)
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_script_style:
            return
        self.parts.append(data)


def _strip_nav(html):
    """ナビ/広告/メニュー等を除去して本文候補だけ残す"""
    html = re.sub(r"<(script|style|noscript|iframe|nav|header|footer)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    return html


def html_to_text(html, container=None):
    """container: (tag, id/class, value) のリスト。最初にマッチした要素の中身だけ抽出"""
    html = _strip_nav(html)
    if container:
        for tag, attr, val in container:
            m = re.search(r'<%s[^>]*%s=["\']%s["\'][^>]*>(.*?)</%s>' % (tag, attr, re.escape(val), tag),
                          html, re.S | re.I)
            if m:
                html = m.group(1)
                break
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    text = "".join(p.parts)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------- wikitext ----------------

def _drop_braces(wt):
    """{{...}} テンプレートを除去 (ネスト対応)"""
    out = []
    depth = 0
    i = 0
    n = len(wt)
    while i < n:
        if wt.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if wt.startswith("}}", i) and depth > 0:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            out.append(wt[i])
        i += 1
    return "".join(out)


def _drop_tags(wt):
    """<ref>...</ref> 等を除去、<br>→改行"""
    wt = re.sub(r"<ref[^>]*/>", " ", wt)
    wt = re.sub(r"<ref[^>]*>.*?</ref>", " ", wt, flags=re.S)
    wt = re.sub(r"<nowiki[^>]*>(.*?)</nowiki>", r"\1", wt, flags=re.S)
    wt = re.sub(r"<syntaxhighlight[^>]*>.*?</syntaxhighlight>", " ", wt, flags=re.S)
    wt = re.sub(r"<gallery[^>]*>.*?</gallery>", " ", wt, flags=re.S)
    wt = re.sub(r"<math[^>]*>.*?</math>", " ", wt, flags=re.S)
    wt = re.sub(r"<poem[^>]*>.*?</poem>", " ", wt, flags=re.S)
    wt = re.sub(r"<(br|hr)\s*/?>", "\n", wt, flags=re.I)
    wt = re.sub(r"</?(table|tr|td|th|div|span|sup|sub|small|center|blockquote|ul|ol|li|dl|dt|dd|p|h[1-6])[^>]*>", " ", wt, flags=re.I)
    return wt


def wikitext_to_text(wt):
    wt = _drop_braces(wt)
    wt = _drop_tags(wt)
    # 表
    wt = re.sub(r"\{\|.*?\|\}", " ", wt, flags=re.S)
    # リンク [[表示|ラベル]] → ラベル / [[ページ]] → ページ
    wt = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", wt)
    wt = re.sub(r"\[\[([^\]]+)\]\]", r"\1", wt)
    wt = re.sub(r"\[(https?://[^\s\]]+)\s+([^\]]+)\]", r"\2", wt)
    wt = re.sub(r"\[(https?://[^\s\]]+)\]", " ", wt)
    # 見出し
    wt = re.sub(r"^(=+)\s*(.*?)\s*\1\s*$", r"\n## \2", wt, flags=re.M)
    # リスト記号
    wt = re.sub(r"^[*#;:]+", "", wt, flags=re.M)
    # コメント
    wt = re.sub(r"<!--.*?-->", " ", wt, flags=re.S)
    # HTML エンティティ
    wt = html_lib.unescape(wt)
    wt = re.sub(r"[ \t\u3000]+", " ", wt)
    wt = re.sub(r"\n{3,}", "\n\n", wt)
    return wt.strip()


# ---------------- chunking ----------------

def chunk_text(text, size=1000, overlap=150):
    """段落ベースでチャンクに分割。長い段落は size でハード分割"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []
    chunks = []
    buf = ""
    for para in paras:
        if len(para) > size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            # ハード分割 (オーバーラップ付き)
            start = 0
            while start < len(para):
                end = start + size
                chunks.append(para[start:end].strip())
                if end >= len(para):
                    break
                start = end - overlap
            continue
        if len(buf) + len(para) + 1 > size and buf:
            chunks.append(buf.strip())
            # オーバーラップ: 前チャンク末尾を引き継ぐ
            tail = buf[-overlap:] if overlap else ""
            buf = (tail + "\n" if tail.strip() else "") + para
        else:
            buf = (buf + "\n" + para).strip()
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if len(c) > 20]
