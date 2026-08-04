# -*- coding: utf-8 -*-
"""メインクローラー: 全Wikiをクロールして corpus/<key>.jsonl に書き出す"""
import argparse
import hashlib
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import WIKIS
from fetch import Fetcher, solve_hikamers_pow
from extract import chunk_text
from adapters import (crawl_mw, crawl_atwiki, crawl_seesaa, crawl_memo,
                      crawl_fc2, crawl_wikiwiki, crawl_wiki3)

ADAPTERS = {
    "mw": crawl_mw,
    "atwiki": crawl_atwiki,
    "seesaa": crawl_seesaa,
    "memo": crawl_memo,
    "fc2": crawl_fc2,
    "wikiwiki": crawl_wikiwiki,
    "wiki3": crawl_wiki3,
}


def doc_id(wiki_key, title, chunk_i):
    h = hashlib.sha256((wiki_key + "|" + title).encode("utf-8")).hexdigest()[:20]
    return f"{wiki_key}|{h}|{chunk_i}"


def crawl_one(cfg, out_path, force=False, chunk_size=1000):
    if os.path.exists(out_path) and not force:
        print(f"  skip (exists): {cfg['key']}")
        return 0
    fetcher = Fetcher(delay=0.4)
    if cfg.get("delay"):
        domain = urllib.parse.urlparse(cfg.get("site", "")).netloc
        if domain:
            fetcher.domain_delays[domain] = cfg["delay"]
    if cfg.get("pow"):
        try:
            solve_hikamers_pow(fetcher)
        except Exception as e:
            print(f"  PoW failed for {cfg['key']}: {e}")
            return 0
    adapter = ADAPTERS[cfg["platform"]]
    n_docs = 0
    n_pages = 0
    tmp = out_path + ".tmp"
    err = None
    with open(tmp, "w", encoding="utf-8") as f:
        try:
            for title, text, url, ns in adapter(cfg, fetcher):
                n_pages += 1
                chunks = chunk_text(text, size=chunk_size)
                for ci, chunk in enumerate(chunks):
                    doc = {
                        "id": doc_id(cfg["key"], title, ci),
                        "wiki": cfg["key"],
                        "wiki_label": cfg["label"],
                        "page_title": title,
                        "url": url,
                        "namespace": ns,
                        "text": chunk,
                    }
                    f.write(json.dumps(doc, ensure_ascii=False) + "\n")
                    n_docs += 1
                if n_pages % 50 == 0:
                    print(f"    {cfg['key']}: {n_pages} pages, {n_docs} chunks")
        except Exception as e:
            err = e
    if err:
        print(f"  ERROR in {cfg['key']}: {err!r}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 0
    os.replace(tmp, out_path)
    print(f"  DONE {cfg['key']}: {n_pages} pages, {n_docs} chunks")
    return n_docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wikis", default="", help="comma-separated keys, empty=all")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--outdir", default=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus")))
    ap.add_argument("--chunk-size", type=int, default=1000)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    wanted = set(k.strip() for k in args.wikis.split(",") if k.strip())
    total = 0
    for cfg in WIKIS:
        if wanted and cfg["key"] not in wanted:
            continue
        print(f"== {cfg['key']} ({cfg['label']})")
        out = os.path.join(args.outdir, cfg["key"] + ".jsonl")
        total += crawl_one(cfg, out, force=args.force, chunk_size=args.chunk_size)
    print(f"TOTAL chunks: {total}")


if __name__ == "__main__":
    main()
