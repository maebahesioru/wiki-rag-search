# -*- coding: utf-8 -*-
"""ヒカマー図書館 (Yahooリアルタイム検索 TSVアーカイブ) の増分インポート + Meilisearch反映

- LIB_ROOT (default /opt/hikamerslibrary/public) の YYYY/*.tsv をスキャン
- .import_state.json より新しい/新規ファイルだけ処理
- corpus_library/hikamerslibrary.jsonl に追記 + Meilisearch (localhost:7700) に upsert
- index.py (wiki用) とは別ディレクトリなので混ざらない
"""
import csv
import glob
import json
import os
import sys
import time

LIB_ROOT = os.environ.get("LIB_ROOT", "/opt/hikamerslibrary/public")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(APP_DIR, "corpus_library")
CORPUS_FILE = os.path.join(CORPUS_DIR, "hikamerslibrary.jsonl")
STATE_FILE = os.path.join(APP_DIR, "..", "hikamerslibrary", ".import_state.json")
SITE_URL = "https://hikamerslibrary.hikamer.f5.si"

try:
    import requests
except ImportError:
    sys.exit("requests required")

def meili_key():
    with open(os.path.join(APP_DIR, ".env")) as f:
        return f.read().strip()

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

def iter_tsv():
    for ydir in sorted(glob.glob(os.path.join(LIB_ROOT, "*"))):
        if not os.path.isdir(ydir):
            continue
        for f in sorted(glob.glob(os.path.join(ydir, "*.tsv"))):
            yield f

def build_docs(relpath, abspath):
    """TSV → doc リスト。id は lib-{tweet_id} で安定"""
    docs = []
    year = relpath.split("/")[0]
    fname = os.path.basename(relpath)
    url = f"{SITE_URL}/{year}/{fname}"
    with open(abspath, encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            text = (row.get("displayText") or "").strip()
            tid = (row.get("id") or "").strip()
            if not text or not tid:
                continue
            created = (row.get("createdAt") or "").strip()
            user = (row.get("userName") or "").strip()
            date = created[:10]
            docs.append({
                "id": "lib-" + tid,
                "wiki": "hikamerslibrary",
                "wiki_label": "ヒカマー図書館",
                "page_title": (user + " (" + date + ")") if user else date,
                "url": url + "#" + tid,
                "namespace": 0,
                "text": text,
                "user": user,
                "date": date,
                "tweet_id": tid,
            })
    return docs

def main():
    os.makedirs(CORPUS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state = load_state()
    changed = []
    for f in iter_tsv():
        rel = os.path.relpath(f, LIB_ROOT).replace("\\", "/")
        mt = int(os.path.getmtime(f))
        if state.get(rel) != mt:
            changed.append((rel, f, mt))
    if not changed:
        print(f"library: no changes ({len(state)} files tracked)")
        return
    print(f"library: {len(changed)} files changed/new, importing...")
    key = meili_key()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    total = 0
    t0 = time.time()
    pending = []  # クロスファイルバッチ (1万件でフラッシュ)

    def flush():
        nonlocal pending
        if not pending:
            return
        r = requests.post("http://localhost:7700/indexes/wiki_rag/documents",
                          json=pending, headers=headers, timeout=300)
        if r.status_code not in (200, 202):
            print(f"  ERROR batch {len(pending)}: {r.status_code} {r.text[:150]}")
            pending = []
            return
        task = r.json()["taskUid"]
        for _ in range(600):
            tr = requests.get(f"http://localhost:7700/tasks/{task}", headers=headers, timeout=30).json()
            if tr.get("status") in ("succeeded", "failed", "canceled"):
                if tr["status"] != "succeeded":
                    print(f"  task {task} {tr['status']}: {tr.get('error')}")
                break
            time.sleep(2)
        pending = []

    for rel, f, mt in changed:
        docs = build_docs(rel, f)
        with open(CORPUS_FILE, "a", encoding="utf-8") as cf:
            for d in docs:
                cf.write(json.dumps(d, ensure_ascii=False) + "\n")
        pending.extend(docs)
        total += len(docs)
        if len(pending) >= 10000:
            flush()
            print(f"  {total} tweets so far ({time.time()-t0:.0f}s)")
        state[rel] = mt
        save_state(state)  # 逐次保存 (中断しても再開可能)
    flush()
    print(f"library DONE: {total} tweets imported ({time.time()-t0:.0f}s)")

if __name__ == "__main__":
    main()
