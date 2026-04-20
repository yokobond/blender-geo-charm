#!/usr/bin/env bash
# build_addon.sh
# prefecture_charm Extension Add-on を zip にパッケージングするスクリプト
#
# 使い方:
#   ./build_addon.sh            # wheels を再ダウンロードせずにパッケージング
#   ./build_addon.sh --refresh  # wheels を削除して再ダウンロードしてからパッケージング
#   ./build_addon.sh --pip-platform <plat> --blender-platform <plat> # CI用クロスビルド

set -euo pipefail

ADDON_DIR="$(cd "$(dirname "$0")" && pwd)/prefecture_charm"
WHEELS_DIR="$ADDON_DIR/wheels"
DIST_DIR="$(cd "$(dirname "$0")" && pwd)/dist"
OUTPUT_ZIP="$DIST_DIR/prefecture_charm.zip"

PYTHON_VERSION="3.11"
REFRESH=0
PIP_PLATFORM=""
BLENDER_PLATFORM=""

# 引数パース
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --refresh) REFRESH=1; shift ;;
        --pip-platform) PIP_PLATFORM="$2"; shift 2 ;;
        --blender-platform) BLENDER_PLATFORM="$2"; shift 2 ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
done

# wheels のパッケージ一覧 (pip package名)
PACKAGES=(
    shapely requests reportlab pillow
    charset-normalizer certifi idna urllib3
)

# --refresh オプションまたは別プラットフォーム指定で wheels を再ダウンロード
if [[ "$REFRESH" == "1" ]] || [[ -n "$PIP_PLATFORM" ]]; then
    echo "==> wheels を削除して再ダウンロードします"
    rm -rf "$WHEELS_DIR"
fi

# wheels ディレクトリが空なら再ダウンロード
if [[ ! -d "$WHEELS_DIR" ]] || [[ -z "$(ls -A "$WHEELS_DIR" 2>/dev/null)" ]]; then
    echo "==> wheels をダウンロード中 (python${PYTHON_VERSION}) ..."
    mkdir -p "$WHEELS_DIR"
    
    PIP_CMD=(pip download "${PACKAGES[@]}" --no-deps --only-binary=:all: --python-version "$PYTHON_VERSION" -d "$WHEELS_DIR")
    if [[ -n "$PIP_PLATFORM" ]]; then
        PIP_CMD+=(--platform "$PIP_PLATFORM")
    fi
    
    "${PIP_CMD[@]}"
    echo "==> wheels ダウンロード完了"
else
    echo "==> wheels はすでに存在します (スキップ)"
fi

# blender_manifest.toml の wheels リストを wheels/ 以下のファイルから自動生成
MANIFEST="$ADDON_DIR/blender_manifest.toml"
echo "==> blender_manifest.toml の wheels リストを更新中..."

# wheels = [...] ブロックを再生成して置き換え
export ADDON_DIR
export BLENDER_PLATFORM
python3 - <<'PYEOF'
import os, re

addon_dir = os.environ.get("ADDON_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "prefecture_charm")
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

# CI用のプラットフォーム書き換え
blender_plat = os.environ.get("BLENDER_PLATFORM", "")
if blender_plat:
    if re.search(r"^platforms\s*=\s*\[.*?\]", new_content, flags=re.MULTILINE):
        new_content = re.sub(r"^platforms\s*=\s*\[.*?\]", f'platforms = ["{blender_plat}"]', new_content, flags=re.MULTILINE)
    else:
        # [build] などのテーブルの中に紛れ込まないよう、wheels直後のルート直下に配置する
        new_content = new_content.replace(wheels_block, f'{wheels_block}\nplatforms = ["{blender_plat}"]\n')

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
cd "$ADDON_DIR"
zip -r "$OUTPUT_ZIP" . \
    --exclude "__pycache__/*" \
    --exclude "*.pyc" \
    --exclude ".DS_Store"

echo ""
echo "完了: $OUTPUT_ZIP"
echo "インストール: Blender > Edit > Preferences > Extensions > Install from Disk"
