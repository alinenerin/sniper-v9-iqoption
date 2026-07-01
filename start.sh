#!/bin/bash
# Patch: sobrescreve o client.py da lib pip com a versão corrigida do repo
SITE_PKG=$(python -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || \
           python -c "import sysconfig; print(sysconfig.get_path('purelib'))")
DEST="$SITE_PKG/iqoptionapi/ws/client.py"
SRC="$(dirname "$0")/iqoptionapi/ws/client.py"

if [ -f "$SRC" ] && [ -f "$DEST" ]; then
  cp "$SRC" "$DEST"
  echo "[start.sh] Patch aplicado: client.py corrigido em $DEST"
else
  echo "[start.sh] AVISO: SRC=$SRC | DEST=$DEST"
fi

exec python app.py
