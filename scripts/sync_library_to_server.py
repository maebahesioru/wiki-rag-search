# -*- coding: utf-8 -*-
"""ヒカマー図書館 TSV → VM 同期スクリプト (PC側で実行)

使い方: python sync_library_to_server.py
- public/2008-2026/*.tsv のうち、前回同期から変更/新規のファイルだけ tar で VM に転送
- VM: /opt/hikamerslibrary/public/ に展開 (その後サーバー側 import_library.py が拾う)
"""
import glob
import json
import os
import subprocess
import sys

SRC = r"C:\Users\maeba\Desktop\hikamerslibrary\public"
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".sync_state.json")
VM = "debian@192.168.1.73"
KEY = os.path.expanduser("~/.ssh/pve_key")
DST = "/opt/hikamerslibrary/public"


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(m):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def main():
    manifest = load_manifest()
    changed = []
    for f in glob.glob(os.path.join(SRC, "*", "*.tsv")):
        rel = os.path.relpath(f, SRC).replace("\\", "/")
        mt = int(os.path.getmtime(f))
        if manifest.get(rel) != mt:
            changed.append((rel, f))
    if not changed:
        print(f"sync: no changes ({len(manifest)} files tracked)")
        return
    print(f"sync: {len(changed)} files to transfer")

    # 変更ファイル一覧を tar -T 用に書く (SRC からの相対パス)
    listfile = os.path.join(os.path.dirname(MANIFEST), ".sync_list.tmp")
    with open(listfile, "w", encoding="utf-8") as lf:
        for rel, _ in changed:
            lf.write(rel.replace("/", os.sep) + "\n")

    tar = subprocess.Popen(
        ["tar", "czf", "-", "-C", SRC, "-T", listfile],
        stdout=subprocess.PIPE,
    )
    ssh = subprocess.Popen(
        ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
         VM, f"sudo mkdir -p {DST} && sudo chown debian:debian {DST} && tar xzf - -C {DST}"],
        stdin=tar.stdout,
    )
    tar.stdout.close()
    tar.wait()
    ssh.wait()
    os.remove(listfile)
    if ssh.returncode != 0:
        print(f"sync ERROR: ssh rc={ssh.returncode}")
        sys.exit(1)
    # マニフェスト更新
    for rel, f in changed:
        manifest[rel] = int(os.path.getmtime(f))
    save_manifest(manifest)
    print(f"sync DONE: {len(changed)} files -> {VM}:{DST}")


if __name__ == "__main__":
    main()
