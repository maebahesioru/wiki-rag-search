# -*- coding: utf-8 -*-
"""増分更新:
- MW系: list=recentchanges で最終更新以降の変更/削除ページだけ処理
- 非MW系 (atwiki/seesaa/memo/fc2/wikiwiki/wiki3): 小規模なので全再クロール
corpus/<key>.jsonl にマージし、削除IDは corpus/updates/<key>.deleted.jsonl に書く
"""
import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "crawler"))

from config import WIKIS
from fetch import Fetcher, solve_hikamers_pow
from extract import chunk_text, wikitext_to_text
from crawl import doc_id, crawl_one
from adapters import _mw_get

STATE_FILE = "corpus/.lastrun.json"
UPDATES_DIR = "corpus/updates"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(outdir):
    p = os.path.join(outdir, ".lastrun.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(outdir, state):
    p = os.path.join(outdir, ".lastrun.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def recentchanges_since(fetcher, cfg, since_iso):
    """since 以降に変更されたタイトルと削除されたタイトルを返す"""
    changed, deleted = set(), set()
    params = {
        "action": "query", "list": "recentchanges",
        "rcprop": "title|timestamp|type|logtype",
        "rclimit": "500", "rcstart": now_iso(), "rcend": since_iso,
        "format": "json", "formatversion": "2",
    }
    for _ in range(200):
        data = _mw_get(fetcher, cfg, params)
        for c in data.get("query", {}).get("recentchanges", []):
            t = c.get("title", "")
            if not t or "|" in t:
                continue
            if c.get("type") == "log" and c.get("logtype") == "delete":
                deleted.add(t)
            elif c.get("type") == "log" and c.get("logtype") == "move":
                deleted.add(t)  # 旧タイトルは消えた扱い (新タイトルは new エントリで拾う)
            else:
                changed.add(t)
        if "continue" in data:
            params.update({k: v for k, v in data["continue"].items()})
        else:
            break
    return changed, deleted


def fetch_texts(fetcher, cfg, titles):
    """タイトル一覧の最新本文を取得 → {title: wikitext}"""
    out = {}
    titles = sorted(titles)
    for i in range(0, len(titles), 20):
        batch = titles[i:i + 20]
        data = _mw_get(fetcher, cfg, {
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "format": "json", "formatversion": "2",
            "titles": "|".join(batch),
        })
        for p in data.get("query", {}).get("pages", []):
            t = p.get("title", "")
            revs = p.get("revisions") or []
            content = ""
            if revs:
                slots = revs[0].get("slots") or {}
                content = (slots.get("main") or {}).get("content", "")
                if not content:
                    content = revs[0].get("*", "")
            out[t] = content or ""
    return out


def merge_updates(outdir, cfg, new_docs, removed_titles):
    """corpus/<key>.jsonl に新ドキュメントをマージ。removed_titles の行は捨て、その id を返す"""
    key = cfg["key"]
    path = os.path.join(outdir, key + ".jsonl")
    removed_ids = []
    changed_titles = {d["page_title"] for d in new_docs} | removed_titles
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                d = json.loads(line)
                if d["page_title"] in changed_titles:
                    removed_ids.append(d["id"])
                    continue
                lines.append(line)
    for doc in new_docs:
        lines.append(json.dumps(doc, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return removed_ids


def update_mw(cfg, fetcher, outdir, since_iso):
    changed, deleted = recentchanges_since(fetcher, cfg, since_iso)
    print(f"  {cfg['key']}: changed={len(changed)} deleted={len(deleted)}")
    if not changed and not deleted:
        return
    texts = fetch_texts(fetcher, cfg, changed)
    new_docs = []
    for title, wt in texts.items():
        if not wt.strip():
            continue
        text = wikitext_to_text(wt)
        ns = 0
        if text.startswith("File:") or ":" in title:
            # 名前空間判定は軽く: タイトルから推測 (実用上問題なし)
            prefix = title.split(":", 1)[0]
            nsmap = {"ファイル": 6, "File": 6, "利用者": 2, "User": 2, "トーク": 1, "Talk": 1}
            ns = nsmap.get(prefix, 0)
        if len(text) < 20 and ns == 6:
            text = title
        elif len(text) < 20:
            continue
        for ci, chunk in enumerate(chunk_text(text)):
            new_docs.append({
                "id": doc_id(cfg["key"], title, ci),
                "wiki": cfg["key"], "wiki_label": cfg["label"],
                "page_title": title,
                "url": cfg["site"] + urllib.parse.quote(title),
                "namespace": ns, "text": chunk,
            })
    removed_ids = merge_updates(outdir, cfg, new_docs, deleted)
    # 削除IDを記録
    os.makedirs(UPDATES_DIR, exist_ok=True)
    if removed_ids:
        with open(os.path.join(UPDATES_DIR, cfg["key"] + ".deleted.jsonl"), "w", encoding="utf-8") as f:
            for rid in removed_ids:
                f.write(json.dumps({"id": rid}) + "\n")
    print(f"  -> {len(new_docs)} chunks added/updated, {len(removed_ids)} ids removed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wikis", default="", help="comma-separated keys, empty=all")
    ap.add_argument("--since-days", type=int, default=7, help="初回取得時の遡り日数")
    ap.add_argument("--outdir", default=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus")))
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    wanted = set(k.strip() for k in args.wikis.split(",") if k.strip())
    state = load_state(args.outdir)
    fetcher = Fetcher(delay=0.4)
    now = now_iso()
    for cfg in WIKIS:
        if wanted and cfg["key"] not in wanted:
            continue
        print(f"== {cfg['key']}")
        if cfg.get("pow"):
            try:
                solve_hikamers_pow(fetcher)
            except Exception as e:
                print(f"  PoW failed: {e}")
                continue
        if cfg["platform"] == "mw":
            since = state.get(cfg["key"]) or (datetime.now(timezone.utc) - timedelta(days=args.since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                update_mw(cfg, fetcher, args.outdir, since)
            except Exception as e:
                print(f"  ERROR: {e!r}")
                continue
        else:
            out = os.path.join(args.outdir, cfg["key"] + ".jsonl")
            try:
                crawl_one(cfg, out, force=True)
            except Exception as e:
                print(f"  ERROR: {e!r}")
                continue
        state[cfg["key"]] = now
    save_state(args.outdir, state)
    print("done")


if __name__ == "__main__":
    main()
