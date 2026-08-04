#!/bin/bash
# Wiki RAG search: 毎日増分更新 (server-side, systemd timer から実行)
cd /opt/wiki-rag-search || exit 1
export PATH="$PWD/venv/bin:$PATH"
MASTER_KEY=$(cat /opt/wiki-rag-search/.env 2>/dev/null | tr -d '\r\n')

echo "=== $(date '+%F %T %Z') ==="
echo "=== update.py (増分更新) ==="
python -u update.py 2>&1 | tail -40
echo
echo "=== index.py (インデックス反映) ==="
python -u index.py --meili http://localhost:7700 --key "$MASTER_KEY" 2>&1 | tail -10
echo "=== done $(date '+%F %T %Z') ==="
