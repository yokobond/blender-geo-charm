"""
都道府県 県境ライン PDF エクスポート補助モジュール
====================================================
県境PDFを生成する Blender Python Script 内部ヘルパーです。
単独のUIや単独エクスポート機能は持たず、
prefecture_keychain.py の STL エクスポート時に利用されます。

必要ライブラリ: requests, shapely, reportlab
"""

import sys
import os

# Blender スクリプティングタブからの場合は ensure_packages を使う
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

try:
    from ensure_packages import ensure_packages
    ensure_packages(
        ["requests", "shapely", "reportlab"],
        script_file=__file__,
    )
except Exception as e:
    print(f"[WARN] ensure_packages 失敗: {e} — すでにインストール済みの場合は無視してください")

# ============================================================
# 設定
# ============================================================

# エクスポートしたい都道府県名
PREFECTURE_NAME = "神奈川県"

# 出力先ディレクトリ (None でホームディレクトリ)
OUTPUT_DIR = None

# 隣接県も薄い線で描画するか
DRAW_NEIGHBORS = True

# ページサイズ: "A4" / "A3" / "letter"
PAGE_SIZE = "A4"

# ページ余白 (mm)
MARGIN_MM = 15.0

# 線の太さ (pt)
LINE_WIDTH_TARGET = 1.5    # 対象県の境界線
LINE_WIDTH_NEIGHBOR = 0.4  # 隣接県の境界線

# 色 (R, G, B) — 0.0〜1.0
COLOR_TARGET = (0.0, 0.0, 0.0)       # 黒
COLOR_NEIGHBOR = (0.65, 0.65, 0.65)  # グレー
# 対象県の塗り潰し色 (None で塗り潰しなし)
COLOR_FILL = (0.94, 0.96, 1.0)       # 薄い青

# 国土数値情報 GeoJSON (dataofjapan/land)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/dataofjapan/land/master/japan.geojson"
)

# ============================================================
# 依存ライブラリ
# ============================================================

import json
import math
import tempfile

import requests
from shapely.geometry import shape, MultiPolygon, Polygon
from shapely.ops import unary_union

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4, A3, letter
from reportlab.lib.colors import Color


# ============================================================
# GeoJSON 取得・パース
# ============================================================

def load_geojson(url: str = GEOJSON_URL) -> dict:
    """GeoJSON をキャッシュ付きで取得"""
    cache_file = os.path.join(tempfile.gettempdir(), "japan_prefectures.geojson")
    if os.path.exists(cache_file):
        print("県境データ: キャッシュから読み込み")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"県境データ取得中: {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def parse_features(geojson: dict) -> dict:
    """GeoJSON → {県名: {geometry, properties}} の辞書"""
    features = {}
    for feat in geojson.get("features", []):
        props = feat.get("properties", {})
        name = props.get("nam_ja") or props.get("N03_001") or props.get("name")
        if name:
            features[name] = {
                "geometry": shape(feat["geometry"]),
                "properties": props,
            }
    return features


def get_prefecture(features: dict, name: str):
    if name in features:
        return features[name]["geometry"]
    for key, val in features.items():
        if name in key or key in name:
            return val["geometry"]
    raise KeyError(f"県が見つかりません: {name!r}")


def get_neighbors(features: dict, target_name: str, buffer_deg: float = 0.1) -> list:
    target = get_prefecture(features, target_name)
    buffered = target.buffer(buffer_deg)
    return [
        name for name, data in features.items()
        if name != target_name
        and name not in target_name
        and target_name not in name
        and buffered.intersects(data["geometry"])
    ]


# ============================================================
# ページサイズ解決
# ============================================================

PAGE_SIZES = {
    "A4": A4,
    "A3": A3,
    "LETTER": letter,
    "letter": letter,
}

def resolve_page_size(size) -> tuple:
    """ページサイズを (幅pt, 高さpt) タプルで返す"""
    if isinstance(size, str):
        return PAGE_SIZES.get(size.upper(), A4)
    # (幅mm, 高さmm) タプル
    w_mm, h_mm = size
    return (w_mm * mm, h_mm * mm)


# ============================================================
# reportlab でジオメトリを描画
# ============================================================

def draw_polygon(c: rl_canvas.Canvas, polygon: Polygon,
                 tx, ty, sx, sy,
                 fill_color=None, stroke_color=(0, 0, 0), line_width=1.0):
    """
    Shapely Polygon を reportlab Canvas に描画する。

    tx, ty : データ座標 → ページ座標の平行移動 (pt)
    sx, sy : スケール (pt/度)
    """
    if polygon.is_empty:
        return

    p = c.beginPath()

    def add_ring(coords, move=True):
        first = True
        for lon, lat in coords:
            px = lon * sx + tx
            py = lat * sy + ty
            if first and move:
                p.moveTo(px, py)
                first = False
            else:
                p.lineTo(px, py)
        p.close()

    add_ring(polygon.exterior.coords, move=True)
    for interior in polygon.interiors:
        add_ring(interior.coords, move=True)

    # スタイル設定
    c.setLineWidth(line_width)
    c.setLineCap(1)  # Round cap
    c.setLineJoin(1) # Round join
    if fill_color:
        c.setFillColor(Color(*fill_color))
    if stroke_color:
        c.setStrokeColor(Color(*stroke_color))

    do_fill = 1 if fill_color else 0
    c.drawPath(p, fill=do_fill, stroke=1)


def draw_geometry(c: rl_canvas.Canvas, geom,
                  tx, ty, sx, sy,
                  fill_color=None, stroke_color=(0, 0, 0), line_width=1.0):
    """Polygon / MultiPolygon を描画"""
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        return
    for poly in polys:
        draw_polygon(c, poly, tx, ty, sx, sy, fill_color, stroke_color, line_width)


# ============================================================
# PDF 出力メイン
# ============================================================

def export_prefecture_pdf(
    prefecture_name: str = PREFECTURE_NAME,
    output_dir: str = None,
    draw_neighbors: bool = DRAW_NEIGHBORS,
    page_size=PAGE_SIZE,
    margin_mm: float = MARGIN_MM,
    exact_bounds: tuple = None,
    exact_diameter_mm: float = None,
    line_width_target: float = LINE_WIDTH_TARGET,
    color_sea: tuple = (0.0, 0.5, 1.0),
    color_land: tuple = (0.0, 0.8, 0.0),
    color_target: tuple = (1.0, 1.0, 0.0),
) -> str:
    """
    都道府県の県境ラインを PDF にエクスポートする。

    Returns:
        出力した PDF のファイルパス
    """
    # --- データ取得 ---
    geojson = load_geojson()
    features = parse_features(geojson)

    target_geom = get_prefecture(features, prefecture_name)
    print(f"対象県: {prefecture_name}  ({type(target_geom).__name__})")

    neighbor_geom = None
    if draw_neighbors:
        neighbor_names = get_neighbors(features, prefecture_name)
        print(f"隣接県: {neighbor_names}")
        if neighbor_names:
            neighbor_geom = unary_union([
                features[n]["geometry"] for n in neighbor_names if n in features
            ])

    # --- ページ・描画エリア ---
    if exact_diameter_mm is not None and exact_bounds is not None:
        lon_min, lat_min, lon_max, lat_max = exact_bounds
        page_w_pt = (exact_diameter_mm + 2 * margin_mm) * mm
        page_h_pt = (exact_diameter_mm + 2 * margin_mm) * mm
        sx = exact_diameter_mm * mm / (lon_max - lon_min)
        sy = exact_diameter_mm * mm / (lat_max - lat_min)
        tx = (margin_mm * mm) - lon_min * sx
        ty = (margin_mm * mm) - lat_min * sy
    else:
        page_w_pt, page_h_pt = resolve_page_size(page_size)
        margin_pt = margin_mm * mm

        draw_w_pt = page_w_pt - 2 * margin_pt
        draw_h_pt = page_h_pt - 2 * margin_pt

        # 対象県の地理的 BBox
        minx, miny, maxx, maxy = target_geom.bounds
        data_w = maxx - minx   # 経度幅 (度)
        data_h = maxy - miny   # 緯度幅 (度)

        # 実距離比補正: 経度1度の実距離 = cos(lat)*111km, 緯度1度 = 111km
        lat_center = (miny + maxy) / 2.0
        lon_scale = math.cos(math.radians(lat_center))

        # スケーリング: アスペクト比を保って描画エリアに収める
        scale_x = draw_w_pt / (data_w * lon_scale)  # pt / (度*cos補正)
        scale_y = draw_h_pt / data_h                 # pt / 度

        if scale_x / lon_scale < scale_y:
            # 横幅いっぱい
            s = scale_x / lon_scale   # pt/度 (経度)
            sx = s * lon_scale        # 経度方向 (実距離比補正)
            sy = s                    # 緯度方向
        else:
            # 縦幅いっぱい
            sy = scale_y
            sx = sy * lon_scale

        map_w_pt = data_w * sx
        map_h_pt = data_h * sy

        # 描画エリア中央に配置するオフセット
        ox = margin_pt + (draw_w_pt - map_w_pt) / 2
        oy = margin_pt + (draw_h_pt - map_h_pt) / 2

        # データ座標 → ページ座標 (reportlab: 左下原点)
        tx = -minx * sx + ox
        ty = -miny * sy + oy

    # --- PDF 生成 ---
    if output_dir is None:
        output_dir = os.path.expanduser("~")
    os.makedirs(output_dir, exist_ok=True)

    safe_name = prefecture_name.replace("/", "_").replace("\\", "_")
    output_path = os.path.join(output_dir, f"prefecture_{safe_name}.pdf")

    c = rl_canvas.Canvas(output_path, pagesize=(page_w_pt, page_h_pt))
    c.setTitle(f"{prefecture_name} 県境")
    c.setAuthor("export_prefecture_pdf.py")

    # 背景 (海)
    c.setFillColor(Color(*color_sea))
    c.rect(0, 0, page_w_pt, page_h_pt, fill=1, stroke=0)

    # 他の陸地 (背面)
    if draw_neighbors:
        for name, data in features.items():
            if name != prefecture_name:
                draw_geometry(
                    c, data["geometry"], tx, ty, sx, sy,
                    fill_color=color_land,
                    stroke_color=COLOR_NEIGHBOR,
                    line_width=LINE_WIDTH_NEIGHBOR,
                )

    # 対象県 (前面)
    draw_geometry(
        c, target_geom, tx, ty, sx, sy,
        fill_color=color_target,
        stroke_color=COLOR_TARGET,
        line_width=line_width_target,
    )

    c.save()
    print(f"\nPDF 出力完了: {output_path}")
    return output_path


# ============================================================
# Blender で実行された場合: prefecture_keychain の UI を登録する
# bpy.app.timers を使い、オペレーター実行中のクラッシュを避けるため
# 次の Blender イベントループで登録する。
# ============================================================
try:
    import bpy as _bpy

    def _register_keychain_ui():
        import sys as _sys
        import os as _os
        try:
            _dir = _os.path.dirname(_os.path.abspath(__file__))
        except NameError:
            # __file__ が未定義の場合は sys.path から探す
            _dir = None
        if _dir and _dir not in _sys.path:
            _sys.path.insert(0, _dir)
        try:
            import prefecture_keychain as _kc
            try:
                _kc.unregister()
            except Exception:
                pass
            _kc.register()
            print("[PDF Export] キーホルダーUIを登録しました (3D Viewport > サイドバー > キーホルダー)")
        except Exception as e:
            print(f"[PDF Export] UI登録エラー: {e}")
        return None  # 1回のみ実行

    _bpy.app.timers.register(_register_keychain_ui, first_interval=0.0)

except ImportError:
    pass  # bpy がない通常 Python 実行の場合は何もしない
