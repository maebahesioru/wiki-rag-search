# -*- coding: utf-8 -*-
"""corpus/*.jsonl → Meilisearch にインデックス (冪等: id ベース upsert)"""
import argparse
import glob
import json
import os
import sys
import time

import requests

INDEX = "wiki_rag"


def wait_task(base, key, task_uid, timeout=300):
    for _ in range(timeout * 2):
        r = requests.get(f"{base}/tasks/{task_uid}", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        t = r.json()
        if t["status"] in ("succeeded", "failed", "canceled"):
            return t["status"], t.get("error")
        time.sleep(0.5)
    return "timeout", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meili", default="http://localhost:7700")
    ap.add_argument("--key", required=True)
    ap.add_argument("--corpus", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus"))
    ap.add_argument("--index", default=INDEX)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    base = args.meili.rstrip("/")
    h = {"Authorization": f"Bearer {args.key}", "Content-Type": "application/json"}

    if args.reset:
        r = requests.delete(f"{base}/indexes/{args.index}", headers=h, timeout=60)
        print("reset:", r.status_code, r.text[:100])

    # settings
    settings = {
        "filterableAttributes": ["wiki", "page_title", "namespace", "url", "date", "user"],
        "searchableAttributes": ["page_title", "text"],
        "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
        "distinctAttribute": None,
    }
    r = requests.patch(f"{base}/indexes/{args.index}/settings", json=settings, headers=h, timeout=60)
    print("settings:", r.status_code, r.json().get("status", r.text[:80]))

    # 削除ID処理 (update.py が corpus/updates/*.deleted.jsonl に書いたもの)
    del_files = sorted(glob.glob(os.path.join(args.corpus, "updates", "*.deleted.jsonl")))
    if del_files:
        ids = []
        for fp in del_files:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ids.append(json.loads(line)["id"].replace("|", "-"))
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            r = requests.post(f"{base}/indexes/{args.index}/documents/delete-batch",
                              json=batch, headers=h, timeout=120)
            if r.status_code not in (200, 202):
                print(f"  delete-batch failed: {r.status_code} {r.text[:200]}")
                sys.exit(1)
            st, err = wait_task(base, args.key, r.json()["taskUid"])
            print(f"  deleted {len(batch)} (task {st})")
        # 処理済み削除ファイルは消す
        for fp in del_files:
            try:
                os.remove(fp)
            except OSError:
                pass

    files = sorted(glob.glob(os.path.join(args.corpus, "*.jsonl")))
    total = 0
    for fp in files:
        docs = []
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                # Meilisearch の ID は英数字と - _ のみ → パイプをハイフンに
                d["id"] = d["id"].replace("|", "-")
                docs.append(d)
        if not docs:
            continue
        for i in range(0, len(docs), 1000):
            batch = docs[i:i + 1000]
            r = requests.post(f"{base}/indexes/{args.index}/documents?primaryKey=id",
                              json=batch, headers=h, timeout=120)
            if r.status_code not in (200, 202):
                print(f"  POST failed: {r.status_code} {r.text[:200]}")
                sys.exit(1)
            st, err = wait_task(base, args.key, r.json()["taskUid"])
            if st != "succeeded":
                print(f"  task {st}: {err}")
                sys.exit(1)
            total += len(batch)
            print(f"  {os.path.basename(fp)}: {total} docs indexed")
    print(f"TOTAL indexed: {total}")


if __name__ == "__main__":
    main()
