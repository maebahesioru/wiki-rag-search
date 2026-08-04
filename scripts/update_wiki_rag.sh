#!/bin/bash
# Wiki RAG 検索エンジン: 毎日増分更新 + インデックス反映
# キーは .meili_master_key (gitignore済み) から読む
cd "$(dirname "$0")/.." || exit 1

KEY_FILE=".meili_master_key"
if [ ! -f "$KEY_FILE" ]; then
  echo "ERROR: $KEY_FILE not found"
  exit 1
fi
MASTER_KEY=$(cat "$KEY_FILE")

echo "=== update.py (増分更新) ==="
python update.py 2>&1 | tail -30
echo
echo "=== index.py (インデックス反映) ==="
python index.py --meili https://wiki-search.hikamer.f5.si --key "$MASTER_KEY" 2>&1 | tail -15
