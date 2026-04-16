#!/usr/bin/env bash
# build_addon.sh
# geo_charm_keychain Extension Add-on を zip にパッケージングするスクリプト
#
# 使い方:
#   ./build_addon.sh            # wheels を再ダウンロードせずにパッケージング
#   ./build_addon.sh --refresh  # wheels を削除して再ダウンロードしてからパッケージング

set -euo pipefail

ADDON_DIR="$(cd "$(dirname "$0")" && pwd)/geo_charm_keychain"
WHEELS_DIR="$ADDON_DIR/wheels"
DIST_DIR="$(cd "$(dirname "$0")" && pwd)/dist"
OUTPUT_ZIP="$DIST_DIR/geo_charm_keychain.zip"

PYTHON_VERSION="3.11"

# wheels のパッケージ一覧 (pip package名)
PACKAGES=(
    shapely
    requests
    reportlab
    pillow
    charset-normalizer
    certifi
    idna
    urllib3
)

# --refresh オプションで wheels を再ダウンロード
if [[ "${1:-}" == "--refresh" ]]; then
    echo "==> wheels を削除して再ダウンロードします"
    rm -rf "$WHEELS_DIR"
fi

# wheels ディレクトリが空なら再ダウンロード
if [[ ! -d "$WHEELS_DIR" ]] || [[ -z "$(ls -A "$WHEELS_DIR" 2>/dev/null)" ]]; then
    echo "==> wheels をダウンロード中 (python${PYTHON_VERSION}) ..."
    mkdir -p "$WHEELS_DIR"
    pip download "${PACKAGES[@]}" \
        --no-deps \
        --only-binary=:all: \
        --python-version "$PYTHON_VERSION" \
        -d "$WHEELS_DIR"
    echo "==> wheels ダウンロード完了"
else
    echo "==> wheels はすでに存在します (スキップ)"
fi

# blender_manifest.toml の wheels リストを wheels/ 以下のファイルから自動生成
MANIFEST="$ADDON_DIR/blender_manifest.toml"
echo "==> blender_manifest.toml の wheels リストを更新中..."

# wheels = [...] ブロックを再生成して置き換え
python3 - <<'PYEOF'
import os, re

addon_dir = os.environ.get("ADDON_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_charm_keychain")
wheels_dir = os.path.join(addon_dir, "wheels")
manifest_path = os.path.join(addon_dir, "blender_manifest.toml")

whl_files = sorted(f for f in os.listdir(wheels_dir) if f.endswith(".whl"))
wheels_lines = ["wheels = ["]
for whl in whl_files:
    wheels_lines.append(f'  "./wheels/{whl}",')
wheels_lines.append("]")
wheels_block = "\n".join(wheels_lines)

with open(manifest_path, "r", encoding="utf-8") as f:
    content = f.read()

# wheels = [ ... ] ブロックを置換 (複数行対応)
new_content = re.sub(r"wheels\s*=\s*\[.*?\]", wheels_block, content, flags=re.DOTALL)

with open(manifest_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"  更新完了: {manifest_path}")
for whl in whl_files:
    print(f"  + {whl}")
PYEOF

# zip を再作成
echo "==> zip を作成中: $OUTPUT_ZIP"
mkdir -p "$DIST_DIR"
rm -f "$OUTPUT_ZIP"
cd "$(dirname "$ADDON_DIR")"
zip -r "$OUTPUT_ZIP" "$(basename "$ADDON_DIR")/" \
    --exclude "$(basename "$ADDON_DIR")/__pycache__/*" \
    --exclude "$(basename "$ADDON_DIR")/*.pyc" \
    --exclude "$(basename "$ADDON_DIR")/.DS_Store"

echo ""
echo "完了: $OUTPUT_ZIP"
echo "インストール: Blender > Edit > Preferences > Extensions > Install from Disk"
