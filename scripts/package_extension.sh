#!/usr/bin/env bash
# 打包 extension/ 成 zip 給其他人安裝（Load unpacked 方式）。
# 用法：bash scripts/package_extension.sh
# 產出：dist/nlm-helper-v{VERSION}.zip（VERSION 自 manifest.json 抓）

set -euo pipefail

cd "$(dirname "$0")/.."

EXT_DIR="extension"
OUT_DIR="dist"

if [[ ! -d "$EXT_DIR" ]]; then
  echo "找不到 $EXT_DIR/ 目錄" >&2
  exit 1
fi

# 從 manifest.json 抓版本號（不依賴 jq，純 grep / sed）
VERSION=$(grep -E '"version"\s*:' "$EXT_DIR/manifest.json" | head -1 | sed -E 's/.*"version"\s*:\s*"([^"]+)".*/\1/')
if [[ -z "$VERSION" ]]; then
  echo "無法從 $EXT_DIR/manifest.json 抓出版本" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
ZIP_NAME="nlm-helper-v${VERSION}.zip"
ZIP_PATH="$OUT_DIR/$ZIP_NAME"

rm -f "$ZIP_PATH"

# 用 python 打包（Windows / Mac / Linux 都通用，不依賴 zip 命令）
python -c "
import os, sys, zipfile, fnmatch
src = 'extension'
out = '$ZIP_PATH'
EXCLUDE_FILES = ['.DS_Store', 'Thumbs.db', '*.pyc', '*.swp']
EXCLUDE_DIRS = ['__pycache__', '.git', 'node_modules']

def is_excluded(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)

count = 0
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if is_excluded(f, EXCLUDE_FILES):
                continue
            full = os.path.join(root, f)
            arc = os.path.relpath(full, '.')
            z.write(full, arc)
            count += 1
print(f'  zipped {count} files')
"

echo ""
echo "✅ 打包完成：$ZIP_PATH"
echo ""
echo "分發給對方時請一併附上 extension/INSTALL.md（已包在 zip 內）。"
echo "對方解壓後依照 INSTALL.md 步驟安裝即可。"
