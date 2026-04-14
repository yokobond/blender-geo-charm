"""
都道府県キーホルダー3Dモデル生成スクリプト (Blender Python Script)
==========================================================
国土地理院の標高タイルデータを利用して、指定した都道府県の
3Dプリント用キーホルダーモデルを自動生成します。

使い方:
  1. Blender を開く
  2. スクリプティングワークスペースに切り替え
  3. このスクリプトを開いて実行 (Alt+P)
  4. UIパネル「キーホルダー生成」がサイドバー(N)に表示される

必要ライブラリ (Blender Python に追加):
  pip install requests numpy shapely

出典: 国土地理院 地理院タイル (https://maps.gsi.go.jp/development/ichiran.html)
"""

import bpy
import bmesh
import math
import os
import json
import struct
import tempfile
from pathlib import Path
from collections import defaultdict

# ============================================================
# 外部ライブラリのインポート（Blender Python 環境で必要）
# ============================================================
try:
    import numpy as np
except ImportError:
    raise ImportError(
        "numpy が必要です。Blender の Python で "
        "'pip install numpy' を実行してください。"
    )

try:
    import requests
except ImportError:
    raise ImportError(
        "requests が必要です。Blender の Python で "
        "'pip install requests' を実行してください。"
    )

try:
    from shapely.geometry import shape, Point, MultiPolygon, Polygon
    from shapely.ops import unary_union
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    print("WARNING: shapely が見つかりません。県境データの自動取得が制限されます。")


# ============================================================
# 定数・設定
# ============================================================

# 国土地理院 標高タイル (テキスト形式, DEM10B)
GSI_DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt"
# DEM5A (より高精度, 航空レーザ測量)
GSI_DEM5A_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.txt"

# Natural Earth / 国土数値情報の代替: 簡易県境データ
# 実運用では国土数値情報の行政区域データ (GeoJSON) を使用推奨
PREFECTURES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/dataofjapan/land/master/japan.geojson"
)

# キーホルダー物理サイズ (mm)
DEFAULT_KEYCHAIN_DIAMETER_MM = 50.0  # 円形土台の直径
DEFAULT_BASE_THICKNESS_MM = 2.0      # 土台の厚さ
DEFAULT_TERRAIN_MAX_HEIGHT_MM = 8.0  # 地形の最大高さ
DEFAULT_HOLE_DIAMETER_MM = 4.0       # キーホルダー穴径
DEFAULT_HOLE_MARGIN_MM = 3.0         # 穴の中心から縁までの距離
DEFAULT_NEIGHBOR_THICKNESS_MM = 0.5  # 隣接県/海の薄い刻印の高さ
DEFAULT_ISLAND_OFFSET_MM = 0.3       # 島パーツの接着しろ凹み
DEFAULT_MAIN_TERRAIN_OFFSET_MM = 2.0       # メイン地形の追加底上げ高さ
DEFAULT_BORDER_GROOVE_DEPTH_MM = 1.0       # 県境の溝の深さ (0.0=溝なし)

DEFAULT_MAP_MARGIN_RATIO = 0.3       # マップの余白比率

# ズームレベル (10 ≈ 約150m解像度, 県全体をカバーするのに適切)
DEFAULT_ZOOM_LEVEL = 10

# 県コード → 名前マッピング (主要なもの)
PREFECTURE_NAMES = {
    1: "北海道", 2: "青森県", 3: "岩手県", 4: "宮城県", 5: "秋田県",
    6: "山形県", 7: "福島県", 8: "茨城県", 9: "栃木県", 10: "群馬県",
    11: "埼玉県", 12: "千葉県", 13: "東京都", 14: "神奈川県", 15: "新潟県",
    16: "富山県", 17: "石川県", 18: "福井県", 19: "山梨県", 20: "長野県",
    21: "岐阜県", 22: "静岡県", 23: "愛知県", 24: "三重県", 25: "滋賀県",
    26: "京都府", 27: "大阪府", 28: "兵庫県", 29: "奈良県", 30: "和歌山県",
    31: "鳥取県", 32: "島根県", 33: "岡山県", 34: "広島県", 35: "山口県",
    36: "徳島県", 37: "香川県", 38: "愛媛県", 39: "高知県", 40: "福岡県",
    41: "佐賀県", 42: "長崎県", 43: "熊本県", 44: "大分県", 45: "宮崎県",
    46: "鹿児島県", 47: "沖縄県",
}


# ============================================================
# ユーティリティ: タイル座標変換
# ============================================================

def latlon_to_tile(lat, lon, zoom):
    """緯度経度 → タイル座標 (x, y)"""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_latlon(x, y, zoom):
    """タイル座標 → 緯度経度 (タイル左上隅)"""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def tile_bounds(x, y, zoom):
    """タイルの範囲 (lat_max, lon_min, lat_min, lon_max)"""
    lat_max, lon_min = tile_to_latlon(x, y, zoom)
    lat_min, lon_max = tile_to_latlon(x + 1, y + 1, zoom)
    return lat_max, lon_min, lat_min, lon_max


# ============================================================
# 標高データ取得
# ============================================================

class ElevationFetcher:
    """国土地理院の標高タイルからDEMデータを取得"""

    def __init__(self, zoom=DEFAULT_ZOOM_LEVEL, use_dem5a=False, cache_dir=None):
        self.zoom = zoom
        self.base_url = GSI_DEM5A_URL if use_dem5a else GSI_DEM_URL
        self.cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "gsi_dem_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._tile_cache = {}

    def _fetch_tile(self, tx, ty):
        """1タイル分の標高データ (256x256) を取得"""
        cache_key = (tx, ty, self.zoom)
        if cache_key in self._tile_cache:
            return self._tile_cache[cache_key]

        # ファイルキャッシュ
        cache_file = os.path.join(
            self.cache_dir, f"dem_{self.zoom}_{tx}_{ty}.npy"
        )
        if os.path.exists(cache_file):
            data = np.load(cache_file)
            # 古いキャッシュに残った異常値も除去
            data[data < -100] = 0.0
            data[data > 8000] = 0.0
            data = np.maximum(data, 0.0)
            self._tile_cache[cache_key] = data
            return data

        url = self.base_url.format(z=self.zoom, x=tx, y=ty)
        print(f"  標高タイル取得中: z={self.zoom}, x={tx}, y={ty}")

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 404:
                # タイルが存在しない → 全て海 (0m)
                data = np.zeros((256, 256), dtype=np.float32)
                self._tile_cache[cache_key] = data
                return data
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  WARNING: タイル取得失敗 ({url}): {e}")
            data = np.zeros((256, 256), dtype=np.float32)
            self._tile_cache[cache_key] = data
            return data

        # テキスト形式パース: 256行, 各行カンマ区切り256値
        data = np.zeros((256, 256), dtype=np.float32)
        lines = resp.text.strip().split('\n')
        for row_idx, line in enumerate(lines[:256]):
            values = line.split(',')
            for col_idx, val in enumerate(values[:256]):
                val = val.strip()
                if val == 'e' or val == '':
                    data[row_idx, col_idx] = 0.0  # 海/データなし
                else:
                    try:
                        data[row_idx, col_idx] = float(val)
                    except ValueError:
                        data[row_idx, col_idx] = 0.0

        # 異常値フィルタ: -9999や極端な負値 (欠損値マーカー) を0に
        data[data < -100] = 0.0
        # 日本の最高地点は富士山3776m、8000m超は無効データ
        data[data > 8000] = 0.0

        # マイナス標高を0に (海面下は3Dプリント上不要)
        data = np.maximum(data, 0.0)

        np.save(cache_file, data)
        self._tile_cache[cache_key] = data
        return data

    def get_elevation_grid(self, lat_min, lat_max, lon_min, lon_max, resolution=256):
        """
        指定範囲の標高グリッドを取得して統合

        Returns:
            elevations: (resolution, resolution) の標高配列 (m)
            (actual_lat_min, actual_lat_max, actual_lon_min, actual_lon_max)
        """
        # 必要タイルの範囲を計算
        tx_min, ty_max = latlon_to_tile(lat_min, lon_min, self.zoom)
        tx_max, ty_min = latlon_to_tile(lat_max, lon_max, self.zoom)

        # 安全マージン
        tx_min -= 1
        ty_min -= 1
        tx_max += 1
        ty_max += 1

        print(f"標高データ取得: タイル範囲 x=[{tx_min}..{tx_max}], y=[{ty_min}..{ty_max}]")
        num_tiles_x = tx_max - tx_min + 1
        num_tiles_y = ty_max - ty_min + 1
        total_px_x = num_tiles_x * 256
        total_px_y = num_tiles_y * 256

        # 全タイルを結合
        full_grid = np.zeros((total_px_y, total_px_x), dtype=np.float32)
        for ty in range(ty_min, ty_max + 1):
            for tx in range(tx_min, tx_max + 1):
                tile_data = self._fetch_tile(tx, ty)
                iy = (ty - ty_min) * 256
                ix = (tx - tx_min) * 256
                full_grid[iy:iy+256, ix:ix+256] = tile_data

        # 実際のタイル範囲の緯度経度
        actual_lat_max, actual_lon_min = tile_to_latlon(tx_min, ty_min, self.zoom)
        actual_lat_min, actual_lon_max = tile_to_latlon(tx_max + 1, ty_max + 1, self.zoom)

        # 指定範囲にクロップ & リサンプル
        # ピクセル座標に変換
        px_x_min = int((lon_min - actual_lon_min) / (actual_lon_max - actual_lon_min) * total_px_x)
        px_x_max = int((lon_max - actual_lon_min) / (actual_lon_max - actual_lon_min) * total_px_x)
        px_y_min = int((actual_lat_max - lat_max) / (actual_lat_max - actual_lat_min) * total_px_y)
        px_y_max = int((actual_lat_max - lat_min) / (actual_lat_max - actual_lat_min) * total_px_y)

        px_x_min = max(0, px_x_min)
        px_x_max = min(total_px_x, px_x_max)
        px_y_min = max(0, px_y_min)
        px_y_max = min(total_px_y, px_y_max)

        cropped = full_grid[px_y_min:px_y_max, px_x_min:px_x_max]

        if cropped.size == 0:
            return np.zeros((resolution, resolution), dtype=np.float32)

        # バイリニア補間でリサンプル
        from numpy import interp
        # 行方向リサンプル
        rows_resampled = np.zeros((resolution, cropped.shape[1]), dtype=np.float32)
        src_rows = np.linspace(0, cropped.shape[0] - 1, resolution)
        for c in range(cropped.shape[1]):
            rows_resampled[:, c] = np.interp(src_rows, np.arange(cropped.shape[0]), cropped[:, c])

        # 列方向リサンプル
        result = np.zeros((resolution, resolution), dtype=np.float32)
        src_cols = np.linspace(0, rows_resampled.shape[1] - 1, resolution)
        for r in range(resolution):
            result[r, :] = np.interp(src_cols, np.arange(rows_resampled.shape[1]), rows_resampled[r, :])

        return result


# ============================================================
# 県境ジオメトリ取得
# ============================================================

class PrefectureBoundary:
    """都道府県の境界ポリゴンを取得・管理"""

    def __init__(self, geojson_path=None):
        self.features = {}
        self._geojson_data = None
        self._geojson_path = geojson_path

    def load_from_url(self, url=PREFECTURES_GEOJSON_URL):
        """GeoJSON をURLからダウンロード"""
        cache_file = os.path.join(
            tempfile.gettempdir(), "japan_prefectures.geojson"
        )
        if os.path.exists(cache_file):
            print("県境データ: キャッシュから読み込み")
            with open(cache_file, 'r', encoding='utf-8') as f:
                self._geojson_data = json.load(f)
        else:
            print(f"県境データ取得中: {url}")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            self._geojson_data = resp.json()
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._geojson_data, f)

        self._parse_features()

    def load_from_file(self, filepath):
        """ローカルの GeoJSON ファイルから読み込み"""
        with open(filepath, 'r', encoding='utf-8') as f:
            self._geojson_data = json.load(f)
        self._parse_features()

    def _parse_features(self):
        """GeoJSON の Feature を県名で辞書化"""
        if not SHAPELY_AVAILABLE:
            print("WARNING: shapely がないため県境ポリゴンの解析をスキップ")
            return

        for feat in self._geojson_data.get('features', []):
            props = feat.get('properties', {})
            # dataofjapan/land の場合: "nam_ja" キー
            name = props.get('nam_ja') or props.get('N03_001') or props.get('name')
            if name:
                geom = shape(feat['geometry'])
                self.features[name] = {
                    'geometry': geom,
                    'properties': props,
                }

    def get_prefecture_polygon(self, name):
        """県名からポリゴンを取得"""
        if name in self.features:
            return self.features[name]['geometry']
        # 部分一致
        for key, val in self.features.items():
            if name in key or key in name:
                return val['geometry']
        return None

    def get_neighbor_prefectures(self, target_name, buffer_deg=0.1):
        """ターゲット県に隣接する県のリストを取得"""
        target = self.get_prefecture_polygon(target_name)
        if target is None:
            return []
        buffered = target.buffer(buffer_deg)
        neighbors = []
        for name, data in self.features.items():
            if name == target_name:
                continue
            if name in target_name or target_name in name:
                continue
            if buffered.intersects(data['geometry']):
                neighbors.append(name)
        return neighbors

    def get_bounds(self, name):
        """県のバウンディングボックス (lon_min, lat_min, lon_max, lat_max)"""
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return None
        return poly.bounds  # (minx, miny, maxx, maxy) = (lon_min, lat_min, lon_max, lat_max)

    def create_mask(self, name, resolution, lon_min, lat_min, lon_max, lat_max):
        """
        県の形状マスク (resolution x resolution) を生成
        県内 = 1.0, 県外 = 0.0
        """
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return np.ones((resolution, resolution), dtype=np.float32)

        mask = np.zeros((resolution, resolution), dtype=np.float32)
        for iy in range(resolution):
            lat = lat_max - (lat_max - lat_min) * iy / (resolution - 1)
            for ix in range(resolution):
                lon = lon_min + (lon_max - lon_min) * ix / (resolution - 1)
                if poly.contains(Point(lon, lat)):
                    mask[iy, ix] = 1.0
        return mask

    def create_other_land_mask(self, target_name, resolution, lon_min, lat_min, lon_max, lat_max):
        """対象県以外の日本の陸地領域マスク"""
        mask = np.zeros((resolution, resolution), dtype=np.float32)
        
        other_union = unary_union([
            data['geometry'] for name, data in self.features.items()
            if name != target_name and name not in target_name and target_name not in name
        ])

        # バウンディングボックスによる事前フィルタ用の矩形
        bounds = other_union.bounds
        other_minx, other_miny, other_maxx, other_maxy = bounds

        for iy in range(resolution):
            lat = lat_max - (lat_max - lat_min) * iy / (resolution - 1)
            if lat < other_miny or lat > other_maxy:
                continue
            for ix in range(resolution):
                lon = lon_min + (lon_max - lon_min) * ix / (resolution - 1)
                if lon < other_minx or lon > other_maxx:
                    continue
                if other_union.contains(Point(lon, lat)):
                    mask[iy, ix] = 1.0
        return mask


    def detect_islands(self, name):
        """
        県のポリゴンから島 (本土から離れた部分) を検出
        Returns: (main_polygon, [island_polygons])
        """
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return None, []

        if isinstance(poly, MultiPolygon):
            parts = list(poly.geoms)
            # 面積最大を本土とする
            parts.sort(key=lambda p: p.area, reverse=True)
            main = parts[0]
            islands = parts[1:]
            # 極小ポリゴンは除外
            islands = [isl for isl in islands if isl.area > main.area * 0.001]
            return main, islands
        else:
            return poly, []


# ============================================================
# Blender 3Dモデル生成
# ============================================================

class KeychainModelBuilder:
    """Blender上にキーホルダー3Dモデルを構築"""

    def __init__(self, config=None):
        self.config = config or {}
        self.diameter_mm = self.config.get('diameter_mm', DEFAULT_KEYCHAIN_DIAMETER_MM)
        self.base_thickness = self.config.get('base_thickness_mm', DEFAULT_BASE_THICKNESS_MM)
        self.terrain_max_height = self.config.get('terrain_max_height_mm', DEFAULT_TERRAIN_MAX_HEIGHT_MM)
        self.hole_diameter = self.config.get('hole_diameter_mm', DEFAULT_HOLE_DIAMETER_MM)
        
        # 指定された穴の内側マージンから、中心から縁までの距離を計算
        hole_inner_margin = self.config.get('hole_inner_margin_mm', 1.0)
        self.hole_margin = hole_inner_margin + (self.hole_diameter / 2.0)
        
        self.neighbor_thickness = self.config.get('neighbor_thickness_mm', DEFAULT_NEIGHBOR_THICKNESS_MM)
        self.island_offset = self.config.get('island_offset_mm', DEFAULT_ISLAND_OFFSET_MM)
        self.main_terrain_offset = self.config.get('main_terrain_offset_mm', DEFAULT_MAIN_TERRAIN_OFFSET_MM)
        self.exaggeration = self.config.get('exaggeration', 2.0)

        # Blender では 1 unit = 1mm と扱う (3Dプリント向け)
        self.scale_factor = 0.001  # mm → m (Blender内部単位)
        self.ground_size_m = 0.0  # マップ範囲の実距離(m)、generate()内で設定される

    def clear_scene(self):
        """シーン内の既存オブジェクトをクリア"""
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

        # コレクション整理
        for col in bpy.data.collections:
            if col.name.startswith("Keychain"):
                bpy.data.collections.remove(col)

    def _create_collection(self, name):
        """Blenderコレクションを作成"""
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
        return col

    def build_circular_base(self, collection):
        """
        円形の透明アクリル土台を生成
        - キーホルダー穴付き
        """
        sf = self.scale_factor
        radius = self.diameter_mm / 2.0 * sf
        thickness = self.base_thickness * sf
        hole_r = self.hole_diameter / 2.0 * sf
        hole_center_offset = radius - self.hole_margin * sf

        # アクリル上面 = Z=0、地形底面 = Z=base_thickness*sf なので交差しない
        base_center_z = -thickness / 2

        # 円柱 (土台)
        bpy.ops.mesh.primitive_cylinder_add(
            radius=radius,
            depth=thickness,
            location=(0, 0, base_center_z),
            vertices=128
        )
        base = bpy.context.active_object
        base.name = "Base_Acrylic"

        # キーホルダー穴 (Boolean差し引き用シリンダー)
        bpy.ops.mesh.primitive_cylinder_add(
            radius=hole_r,
            depth=thickness * 10,  # 地形も貫通させるために十分に長くする
            location=(0, hole_center_offset, 0),
            vertices=64
        )
        hole = bpy.context.active_object
        hole.name = "Keychain_Hole_Cutter"
        hole.display_type = 'WIRE'
        hole.hide_render = True
        self.hole_cutter = hole

        # Boolean Modifier で穴を開ける (独立オブジェクトとして残すため適用しない)
        bool_mod = base.modifiers.new(name="Hole", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = hole
        # Blender バージョンで solver 名が異なる:
        #   4.5+: FLOAT / EXACT / MANIFOLD
        #   3.x-4.4: FAST / EXACT
        for solver_name in ('EXACT', 'FLOAT', 'FAST'):
            try:
                bool_mod.solver = solver_name
                break
            except TypeError:
                continue

        # カッターオブジェクトをコレクションに移動
        for c in hole.users_collection:
            c.objects.unlink(hole)
        collection.objects.link(hole)

        # 透明アクリルマテリアル
        mat = bpy.data.materials.new(name="Acrylic_Clear")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        # Principled BSDF
        output = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.95, 0.97, 1.0, 1.0)
        bsdf.inputs['Alpha'].default_value = 0.15
        bsdf.inputs['Roughness'].default_value = 0.05
        bsdf.inputs['IOR'].default_value = 1.49  # アクリル
        # Transmission は Principled BSDF v4.0+ で名称変更の可能性
        try:
            bsdf.inputs['Transmission Weight'].default_value = 0.9
        except KeyError:
            try:
                bsdf.inputs['Transmission'].default_value = 0.9
            except KeyError:
                pass
        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

        mat.blend_method = 'BLEND' if hasattr(mat, 'blend_method') else None
        base.data.materials.append(mat)

        # コレクションに移動
        for c in base.users_collection:
            c.objects.unlink(base)
        collection.objects.link(base)

        return base

    def build_terrain_mesh(self, elevations, mask, collection,
                           name="Terrain_Main", height_scale=None,
                           material_color=(0.4, 0.35, 0.28, 1.0),
                           z_offset_mm=0.0):
        """
        標高グリッドから地形メッシュを生成

        Args:
            elevations: (N, N) 標高データ (m)
            mask: (N, N) 県マスク (1=県内, 0=県外)
            collection: Blender コレクション
            name: オブジェクト名
            height_scale: 高さスケール (Noneなら自動計算)
            material_color: マテリアルの基本色
        """
        sf = self.scale_factor
        radius = self.diameter_mm / 2.0 * sf
        resolution = elevations.shape[0]

        # 標高の正規化: マスク内の値を使い、外れ値を95パーセンタイルでクランプ
        masked_vals = elevations[mask > 0.5]
        if masked_vals.size > 0 and masked_vals.max() > 0:
            elev_max = float(np.percentile(masked_vals, 95))
            # 外れ値クランプ: 95パーセンタイルを超える値を上限に揃える
            elevations = np.clip(elevations, 0.0, elev_max * 1.5)
        else:
            elev_max = float(elevations.max())
        if elev_max <= 0:
            elev_max = 1.0

        if height_scale is None:
            if hasattr(self, 'ground_size_m') and self.ground_size_m > 0:
                # 実スケールに基づく高さ計算 (exaggeration=1.0で現実と同じ比率)
                height_scale = (self.diameter_mm * sf / self.ground_size_m) * self.exaggeration
            else:
                height_scale = self.terrain_max_height * sf * self.exaggeration / elev_max

        # メッシュ作成
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)

        bm = bmesh.new()

        # 頂点作成: グリッドを円形にマッピング
        verts = {}
        for iy in range(resolution):
            for ix in range(resolution):
                # 正規化座標 [-1, 1]
                nx = (ix / (resolution - 1)) * 2.0 - 1.0
                ny = (iy / (resolution - 1)) * 2.0 - 1.0

                # 円内のみ
                dist = math.sqrt(nx * nx + ny * ny)
                if dist > 1.0:
                    continue

                # マスクチェック
                if mask[iy, ix] < 0.5:
                    continue

                # 位置 (円形にフィット)
                # 地形をアクリル上面(Z=0)の真上に載せる
                x = nx * radius
                y = -ny * radius  # Y反転 (北が上)
                z = (z_offset_mm * sf) + elevations[iy, ix] * height_scale

                v = bm.verts.new((x, y, z))
                verts[(ix, iy)] = v

        bm.verts.ensure_lookup_table()

        # 面作成 (四角形 → 三角形分割)
        for iy in range(resolution - 1):
            for ix in range(resolution - 1):
                v00 = verts.get((ix, iy))
                v10 = verts.get((ix + 1, iy))
                v01 = verts.get((ix, iy + 1))
                v11 = verts.get((ix + 1, iy + 1))

                if v00 and v10 and v11:
                    try:
                        bm.faces.new([v00, v10, v11])
                    except ValueError:
                        pass
                if v00 and v11 and v01:
                    try:
                        bm.faces.new([v00, v11, v01])
                    except ValueError:
                        pass

        bm.to_mesh(mesh)
        bm.free()

        # 底面を追加してソリッドにする (3Dプリント用)
        # アクリル上面(Z=0)を底とする
        self._add_solid_bottom(obj, target_z=0.0)

        # 穴カッターで地形もくり抜く
        if hasattr(self, 'hole_cutter') and self.hole_cutter:
            bool_mod = obj.modifiers.new(name="Hole", type='BOOLEAN')
            bool_mod.operation = 'DIFFERENCE'
            bool_mod.object = self.hole_cutter
            for solver_name in ('EXACT', 'FLOAT', 'FAST'):
                try:
                    bool_mod.solver = solver_name
                    break
                except TypeError:
                    continue

        # マテリアル
        mat = bpy.data.materials.new(name=f"Material_{name}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = material_color
            bsdf.inputs['Roughness'].default_value = 0.7
        obj.data.materials.append(mat)

        return obj

    def build_other_land_engraving(self, elevations, mask, collection, z_offset_mm=0.0):
        """
        他の陸地の部分 (海と陸の隙間を見せるため、適度な厚みを持たせる)
        """
        color = self.config.get('pdf_color_land', (0.1, 0.8, 0.2, 1.0))
        # アクリルベースが見えるように十分な厚み(0.5mm)を出す
        flat_elevations = np.full_like(elevations, 0.5)
        return self.build_terrain_mesh(
            flat_elevations, mask, collection,
            name="Other_Land_Engraving",
            height_scale=self.scale_factor,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

    def build_sea_indication(self, elevations, sea_mask, collection, z_offset_mm=0.0):
        """
        海の領域を表示 (アクリルベースが見えるように適度な厚みを持たせる)
        """
        sf = self.scale_factor
        color = self.config.get('pdf_color_sea', (0.0, 0.5, 1.0, 1.0))
        # アクリルベースが見えるように十分な厚み(0.5mm)を出す
        flat_sea = np.full_like(elevations, 0.5)

        return self.build_terrain_mesh(
            flat_sea, sea_mask, collection,
            name="Sea_Surface",
            height_scale=sf,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

    def build_island_piece(self, elevations, island_mask, collection, island_idx=0, z_offset_mm=0.0):
        """
        島パーツ (別体として生成、接着用の凹みつき)
        """
        name = f"Island_{island_idx}"
        color = self.config.get('pdf_color_target', (1.0, 0.8, 0.0, 1.0))
        obj = self.build_terrain_mesh(
            elevations, island_mask, collection,
            name=name,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

        # 接着面の凹みマーカー (底面を少し下に伸ばす)
        # _add_solid_bottomでZ=0になっている底面を、設定値だけ下げる(アクリルに埋まるように)
        if obj and obj.data.vertices:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            
            # 底面頂点（Z=0）を island_offset 分だけ下げる
            sf = self.scale_factor
            bottom_z = 0.0
            island_z = -self.island_offset * sf
            for v in bm.verts:
                if abs(v.co.z - bottom_z) < 1e-5:
                    v.co.z = island_z
                    
            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

        return obj

    def _add_solid_bottom(self, obj, target_z=0.0):
        """
        メッシュの底面を閉じてソリッド化 (3Dプリント用)
        全面を下方に押し出し、新しい頂点を target_z に揃えて底面を作る。
        """
        if not obj.data.vertices:
            return

        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if not bm.faces:
            bpy.ops.object.mode_set(mode='OBJECT')
            return

        # 全面を押し出し → 側壁と底面コピーが生成される
        extrude_res = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])

        # 押し出しで生成された新頂点を target_z に移動
        new_verts = [e for e in extrude_res['geom'] if isinstance(e, bmesh.types.BMVert)]
        new_faces = [e for e in extrude_res['geom'] if isinstance(e, bmesh.types.BMFace)]
        for v in new_verts:
            v.co.z = target_z

        # 底面の法線を下向きに反転
        bmesh.ops.reverse_faces(bm, faces=new_faces)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

    def add_keychain_ring_preview(self, collection):
        """キーリングのプレビュー用トーラス"""
        sf = self.scale_factor
        radius = self.diameter_mm / 2.0 * sf
        hole_center_y = radius - self.hole_margin * sf

        major_r = self.hole_diameter * sf * 0.8
        bpy.ops.mesh.primitive_torus_add(
            major_radius=major_r,
            minor_radius=0.5 * sf,
            location=(0, hole_center_y + major_r, 0),
            rotation=(0, math.pi / 2, 0)
        )
        ring = bpy.context.active_object
        ring.name = "Keyring_Preview"

        mat = bpy.data.materials.new(name="Metal_Ring")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = (0.8, 0.8, 0.75, 1.0)
            bsdf.inputs['Metallic'].default_value = 1.0
            bsdf.inputs['Roughness'].default_value = 0.2
        ring.data.materials.append(mat)

        for c in ring.users_collection:
            c.objects.unlink(ring)
        collection.objects.link(ring)

        return ring


# ============================================================
# メインオーケストレーション
# ============================================================

class KeychainGenerator:
    """全体を統括するジェネレータ"""

    def __init__(self, prefecture_name="神奈川県", config=None):
        self.prefecture_name = prefecture_name
        self.config = config or {}
        self.zoom = self.config.get('zoom', DEFAULT_ZOOM_LEVEL)
        self.resolution = self.config.get('resolution', 200)
        self.exaggeration = self.config.get('exaggeration', 2.0)
        self.margin_ratio = self.config.get('margin_ratio', DEFAULT_MAP_MARGIN_RATIO)

        self.fetcher = ElevationFetcher(zoom=self.zoom)
        self.boundary = PrefectureBoundary()
        self.builder = KeychainModelBuilder({
            **self.config,
            'exaggeration': self.exaggeration,
        })

    def generate(self):
        """キーホルダーモデルを生成"""
        print(f"\n{'='*60}")
        print(f"  キーホルダー生成: {self.prefecture_name}")
        print(f"  標高誇張: {self.exaggeration}倍")
        print(f"  解像度: {self.resolution}x{self.resolution}")
        print(f"{'='*60}\n")

        # 1. シーンクリア
        print("[1/7] シーンをクリア中...")
        self.builder.clear_scene()

        # 2. 県境データ取得
        print("[2/7] 県境データを取得中...")
        try:
            self.boundary.load_from_url()
        except Exception as e:
            print(f"  県境データ取得失敗: {e}")
            print("  → 矩形範囲で代替します")

        # 3. 県のバウンディングボックスを取得
        print("[3/7] 対象県の範囲を計算中...")
        bounds = self.boundary.get_bounds(self.prefecture_name)
        if bounds:
            lon_min, lat_min, lon_max, lat_max = bounds
            # マージンを追加 (隣接県表示のため)
            margin = max(lon_max - lon_min, lat_max - lat_min) * self.margin_ratio
            lon_min -= margin
            lat_min -= margin
            lon_max += margin
            lat_max += margin
        else:
            # 神奈川県のデフォルト座標
            lat_min, lat_max = 35.12, 35.67
            lon_min, lon_max = 138.91, 139.79
            margin = 0.15 * (self.margin_ratio / 0.3) if self.margin_ratio != 0.3 else 0.15 # Scale default margin roughly based on ratio
            lon_min -= margin
            lat_min -= margin
            lon_max += margin
            lat_max += margin

        # アスペクト比を1:1に調整 (円形土台のため)
        lat_center = (lat_min + lat_max) / 2
        lon_center = (lon_min + lon_max) / 2
        span = max(lat_max - lat_min, (lon_max - lon_min) * math.cos(math.radians(lat_center)))
        # 経度方向の補正
        lon_span = span / math.cos(math.radians(lat_center))
        lat_min = lat_center - span / 2
        lat_max = lat_center + span / 2
        lon_min = lon_center - lon_span / 2
        lon_max = lon_center + lon_span / 2

        # 現実のサイズ (m)
        self.builder.ground_size_m = span * 111000

        print(f"  範囲: lat=[{lat_min:.4f}, {lat_max:.4f}], lon=[{lon_min:.4f}, {lon_max:.4f}]")

        # 4. 標高データ取得
        print("[4/7] 標高データを取得中...")
        elevations = self.fetcher.get_elevation_grid(
            lat_min, lat_max, lon_min, lon_max,
            resolution=self.resolution
        )
        print(f"  標高範囲: {elevations.min():.1f}m 〜 {elevations.max():.1f}m")

        # 5. マスク生成
        print("[5/7] 県境マスクを生成中...")
        if SHAPELY_AVAILABLE and self.boundary.features:
            main_mask = self.boundary.create_mask(
                self.prefecture_name, self.resolution,
                lon_min, lat_min, lon_max, lat_max
            )
            other_land_mask = self.boundary.create_other_land_mask(
                self.prefecture_name, self.resolution,
                lon_min, lat_min, lon_max, lat_max
            )
            # 海マスク: 対象県でも他の陸地でもない
            sea_mask = np.ones_like(main_mask)
            sea_mask[main_mask > 0.5] = 0
            sea_mask[other_land_mask > 0.5] = 0
            
            # 海マスクを侵食して、海の縁を陸から離す
            # sea_land_gap_mm 分だけ海マスクをerodeすることで、
            # 海が陸地の縁から離れ、間にアクリル土台が見える隙間ができる
            gap_mm = self.config.get('sea_land_gap_mm', 0.0)
            # 1ピクセルがキーホルダー上で何mmに相当するか
            # グリッド(resolution×resolution)はキーホルダー直径(diameter_mm)にマッピングされる
            pixel_size_mm = self.builder.diameter_mm / self.resolution
            gap_px = max(1, int(round(gap_mm / pixel_size_mm))) if gap_mm > 0 else 0

            def _erode(m, iters):
                if iters <= 0 or m.max() == 0:
                    return m
                t = np.copy(m)
                for _ in range(iters):
                    nt = np.copy(t)
                    nt[1:, :] = np.minimum(nt[1:, :], t[:-1, :])
                    nt[:-1, :] = np.minimum(nt[:-1, :], t[1:, :])
                    nt[:, 1:] = np.minimum(nt[:, 1:], t[:, :-1])
                    nt[:, :-1] = np.minimum(nt[:, :-1], t[:, 1:])
                    t = nt
                return t

            # 海マスクをerodeして陸地との間に隙間を作る（陸地マスクは変更しない）
            sea_mask = _erode(sea_mask, gap_px)

            # 円形にクリップ
            for iy in range(self.resolution):
                for ix in range(self.resolution):
                    nx = (ix / (self.resolution - 1)) * 2.0 - 1.0
                    ny = (iy / (self.resolution - 1)) * 2.0 - 1.0
                    if nx*nx + ny*ny > 1.0:
                        sea_mask[iy, ix] = 0
                        other_land_mask[iy, ix] = 0
        else:
            # shapely なしの場合: 全域を地形として表示
            main_mask = np.ones((self.resolution, self.resolution), dtype=np.float32)
            other_land_mask = np.zeros_like(main_mask)
            sea_mask = np.zeros_like(main_mask)

        # 6. Blenderモデル構築
        print("[6/7] 3Dモデルを構築中...")
        col = self.builder._create_collection(f"Keychain_{self.prefecture_name}")

        # 土台
        print("  → 円形土台...")
        base = self.builder.build_circular_base(col)

        # メイン地形の追加底上げ量
        main_terrain_offset_value = self.config.get('main_terrain_offset_mm', DEFAULT_MAIN_TERRAIN_OFFSET_MM)
        
        # 海や隣接県は Z=0 の基準に合わせる
        base_z_offset = 0.0
        main_z_offset = base_z_offset + main_terrain_offset_value

        # メイン地形
        print("  → メイン地形...")
        color_target = self.config.get('pdf_color_target', (1.0, 0.8, 0.0, 1.0))
        terrain = self.builder.build_terrain_mesh(elevations, main_mask, col, z_offset_mm=main_z_offset, material_color=color_target)

        # 他の陸地の薄い刻印
        if other_land_mask.max() > 0:
            print("  → 他の陸地の表示...")
            self.builder.build_other_land_engraving(elevations, other_land_mask, col, z_offset_mm=base_z_offset)

        # 海の表示
        if sea_mask.max() > 0:
            print("  → 海の表示...")
            self.builder.build_sea_indication(elevations, sea_mask, col, z_offset_mm=base_z_offset)

        # 島の分離
        if SHAPELY_AVAILABLE and self.boundary.features:
            main_poly, islands = self.boundary.detect_islands(self.prefecture_name)
            if islands:
                print(f"  → {len(islands)}個の島パーツを分離...")
                for idx, island_poly in enumerate(islands):
                    # 島用マスクを生成
                    island_mask = np.zeros((self.resolution, self.resolution), dtype=np.float32)
                    for iy in range(self.resolution):
                        lat = lat_max - (lat_max - lat_min) * iy / (self.resolution - 1)
                        for ix in range(self.resolution):
                            lon = lon_min + (lon_max - lon_min) * ix / (self.resolution - 1)
                            if island_poly.contains(Point(lon, lat)):
                                island_mask[iy, ix] = 1.0
                    
                    if island_mask.max() > 0:
                        self.builder.build_island_piece(
                            elevations, island_mask, col, island_idx=idx, z_offset_mm=main_z_offset
                        )

        # キーリングプレビュー
        self.builder.add_keychain_ring_preview(col)

        # 7. ビュー設定
        print("[7/7] ビューを設定中...")
        self._setup_viewport()

        print(f"\n{'='*60}")
        print(f"  完成！ コレクション '{col.name}' に生成されました")
        print(f"  STL エクスポート: ファイル → エクスポート → STL")
        print(f"  出典: 国土地理院 地理院タイル")
        print(f"{'='*60}\n")

        return col

    def _setup_viewport(self):
        """3Dビューポートの設定"""
        # カメラを上から見下ろす位置に
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                        region = space.region_3d
                        if region:
                            region.view_perspective = 'PERSP'
                            region.view_distance = 0.1
                break

    def export_stl(self, filepath=None):
        """STL ファイルにエクスポート"""
        import os
        import sys
        import bpy
        
        if filepath is None:
            filepath = os.path.join(
                os.path.expanduser("~"),
                f"keychain_{self.prefecture_name}.stl"
            )

        # ユーザーがディレクトリのみを選択し、ファイル名が空の場合に対処
        if os.path.isdir(filepath):
            filepath = os.path.join(filepath, f"keychain_{self.prefecture_name}.stl")
        elif not filepath.lower().endswith(".stl"):
            filepath += ".stl"

        # メインパーツのみ選択 (View Layer に属するオブジェクトのみ)
        bpy.ops.object.select_all(action='DESELECT')
        view_layer_objects = bpy.context.view_layer.objects
        for obj in view_layer_objects:
            if obj.type == 'MESH' and not obj.name.startswith("Keyring") and not obj.name.startswith("Keychain_Hole_Cutter"):
                obj.select_set(True)

        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=True,
            global_scale=1.0,
            ascii_format=False
        )
        print(f"STL エクスポート完了: {filepath}")

        # --- STLと同じディレクトリに土台用PDFをエクスポートする ---
        output_dir = os.path.dirname(filepath)
        
        # URLから直接ダウンロードできない場合は、ローカルのキャッシュから読み込みを試みる
        try:
            self.boundary.load_from_url()
        except Exception:
            pass

        bounds = self.boundary.get_bounds(self.prefecture_name)
        if bounds:
            lon_min, lat_min, lon_max, lat_max = bounds
            margin = max(lon_max - lon_min, lat_max - lat_min) * self.margin_ratio
            lon_min -= margin
            lat_min -= margin
            lon_max += margin
            lat_max += margin
        else:
            lat_min, lat_max = 35.12, 35.67
            lon_min, lon_max = 138.91, 139.79
            margin = 0.15 * (self.margin_ratio / 0.3) if self.margin_ratio != 0.3 else 0.15
            lon_min -= margin
            lat_min -= margin
            lon_max += margin
            lat_max += margin

        lat_center = (lat_min + lat_max) / 2
        lon_center = (lon_min + lon_max) / 2
        span = max(lat_max - lat_min, (lon_max - lon_min) * math.cos(math.radians(lat_center)))
        lon_span = span / math.cos(math.radians(lat_center))
        lat_min = lat_center - span / 2
        lat_max = lat_center + span / 2
        lon_min = lon_center - lon_span / 2
        lon_max = lon_center + lon_span / 2

        print(f"  → 土台用PDFを {output_dir} にエクスポート中...")
        try:
            # 外部スクリプトをインポートできるようにディレクトリをパスに追加
            script_dir = ""
            if "__file__" in globals():
                script_dir = os.path.dirname(os.path.abspath(__file__))
            else:
                # Blenderのテキストエディタから実行されている場合への対応
                for text in bpy.data.texts:
                    if text.name == "prefecture_keychain.py" and text.filepath:
                        script_dir = os.path.dirname(bpy.path.abspath(text.filepath))
                        break
            
            if script_dir and script_dir not in sys.path:
                sys.path.insert(0, script_dir)
                
            from export_prefecture_pdf import export_prefecture_pdf
            pdf_path = export_prefecture_pdf(
                prefecture_name=self.prefecture_name,
                output_dir=output_dir,
                margin_mm=1.0,
                exact_bounds=(lon_min, lat_min, lon_max, lat_max),
                exact_diameter_mm=self.builder.diameter_mm,
                line_width_target=self.config.get('pdf_line_width_pt', 1.5),
                color_sea=self.config.get('pdf_color_sea', (0.0, 0.5, 1.0)),
                color_land=self.config.get('pdf_color_land', (0.0, 0.8, 0.0)),
                color_target=self.config.get('pdf_color_target', (1.0, 1.0, 0.0))
            )
            print(f"  → PDF出力完了: {pdf_path}")
        except ImportError:
            print("  → export_prefecture_pdf.py が見つからなかったため、PDF出力をスキップしました。")
        except Exception as e:
            print(f"  → PDF出力エラー: {e}")


# ============================================================
# Blender UIパネル (オプション)
# ============================================================

class KEYCHAIN_PT_MainPanel(bpy.types.Panel):
    bl_label = "キーホルダー生成"
    bl_idname = "KEYCHAIN_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "キーホルダー"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="都道府県キーホルダー生成", icon='MESH_DATA')
        layout.separator()

        # 県選択
        layout.prop(scene, "keychain_prefecture", text="都道府県")

        # パラメータ
        box = layout.box()
        box.label(text="パラメータ", icon='PREFERENCES')
        box.prop(scene, "keychain_exaggeration", text="標高誇張倍率")
        box.prop(scene, "keychain_margin_ratio", text="マージン比率")
        box.prop(scene, "keychain_diameter", text="直径 (mm)")
        box.prop(scene, "keychain_pdf_color_sea", text="海の色")
        box.prop(scene, "keychain_pdf_color_land", text="他の陸地の色")
        box.prop(scene, "keychain_pdf_color_target", text="対象県の色")
        box.prop(scene, "keychain_hole_inner_margin", text="穴の内側マージン (mm)")
        box.prop(scene, "keychain_main_terrain_offset", text="対象県の底上げ高さ (mm)")
        box.prop(scene, "keychain_sea_land_gap", text="海と陸の隙間 (mm)")
        box.prop(scene, "keychain_pdf_line_width", text="PDFの線の太さ (pt)")
        box.prop(scene, "keychain_resolution", text="解像度")

        box.prop(scene, "keychain_zoom", text="タイルズームレベル")

        layout.separator()

        # 生成ボタン
        layout.operator("keychain.generate", text="キーホルダーを生成", icon='PLAY')
        layout.operator("keychain.export_stl", text="STL エクスポート", icon='EXPORT')


class KEYCHAIN_OT_Generate(bpy.types.Operator):
    bl_idname = "keychain.generate"
    bl_label = "キーホルダー生成"
    bl_description = "選択した都道府県のキーホルダー3Dモデルを生成"

    def execute(self, context):
        scene = context.scene
        config = {
            'exaggeration': scene.keychain_exaggeration,
            'margin_ratio': scene.keychain_margin_ratio,
            'diameter_mm': scene.keychain_diameter,
            'hole_diameter_mm': scene.keychain_hole_diameter,
            'hole_inner_margin_mm': scene.keychain_hole_inner_margin,
            'main_terrain_offset_mm': scene.keychain_main_terrain_offset,
            'sea_land_gap_mm': scene.keychain_sea_land_gap,
            'pdf_line_width_pt': scene.keychain_pdf_line_width,
            'pdf_color_sea': tuple(list(scene.keychain_pdf_color_sea) + [1.0]),
            'pdf_color_land': tuple(list(scene.keychain_pdf_color_land) + [1.0]),
            'pdf_color_target': tuple(list(scene.keychain_pdf_color_target) + [1.0]),
            'resolution': scene.keychain_resolution,
            'zoom': scene.keychain_zoom,
        }

        try:
            gen = KeychainGenerator(
                prefecture_name=scene.keychain_prefecture,
                config=config
            )
            gen.generate()
            self.report({'INFO'}, f"{scene.keychain_prefecture}のキーホルダーを生成しました")
        except Exception as e:
            self.report({'ERROR'}, f"生成エラー: {str(e)}")
            import traceback
            traceback.print_exc()

        return {'FINISHED'}


class KEYCHAIN_OT_ExportSTL(bpy.types.Operator):
    bl_idname = "keychain.export_stl"
    bl_label = "STL エクスポート"
    bl_description = "生成したモデルをSTLファイルにエクスポート"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        self.filepath = f"keychain_{context.scene.keychain_prefecture}.stl"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        config = {
            'exaggeration': scene.keychain_exaggeration,
            'margin_ratio': scene.keychain_margin_ratio,
            'diameter_mm': scene.keychain_diameter,
            'hole_diameter_mm': scene.keychain_hole_diameter,
            'hole_inner_margin_mm': scene.keychain_hole_inner_margin,
            'main_terrain_offset_mm': scene.keychain_main_terrain_offset,
            'sea_land_gap_mm': scene.keychain_sea_land_gap,
            'pdf_line_width_pt': scene.keychain_pdf_line_width,
            'pdf_color_sea': tuple(list(scene.keychain_pdf_color_sea) + [1.0]),
            'pdf_color_land': tuple(list(scene.keychain_pdf_color_land) + [1.0]),
            'pdf_color_target': tuple(list(scene.keychain_pdf_color_target) + [1.0]),
            'resolution': scene.keychain_resolution,
            'zoom': scene.keychain_zoom,
        }
        gen = KeychainGenerator(scene.keychain_prefecture, config=config)
        gen.export_stl(self.filepath)
        self.report({'INFO'}, f"STL エクスポート完了: {self.filepath}")
        return {'FINISHED'}


# プロパティ定義
PREFECTURE_ITEMS = [(name, name, "") for code, name in sorted(PREFECTURE_NAMES.items())]


def register():
    bpy.types.Scene.keychain_prefecture = bpy.props.EnumProperty(
        name="都道府県",
        items=PREFECTURE_ITEMS,
        default="神奈川県"
    )
    bpy.types.Scene.keychain_exaggeration = bpy.props.FloatProperty(
        name="標高誇張倍率",
        default=3.0, min=1.0, max=10.0, step=10,
        description="標高の誇張倍率 (1.0=実スケール, 3.0=3倍)"
    )
    bpy.types.Scene.keychain_margin_ratio = bpy.props.FloatProperty(
        name="マージン比率",
        default=0.3, min=0.0, max=1.0, step=5,
        description="周辺の余白の広さ (0.0で余白なし)"
    )
    bpy.types.Scene.keychain_diameter = bpy.props.FloatProperty(
        name="直径 (mm)",
        default=50.0, min=30.0, max=100.0, step=100,
        description="円形土台の直径"
    )
    bpy.types.Scene.keychain_hole_diameter = bpy.props.FloatProperty(
        name="穴の直径 (mm)",
        default=4.0, min=1.0, max=20.0, step=100,
        description="キーホルダーを通す穴の直径"
    )
    bpy.types.Scene.keychain_hole_inner_margin = bpy.props.FloatProperty(
        name="穴の内側マージン (mm)",
        default=1.0, min=0.0, max=10.0, step=10,
        description="リング穴の内側の端から土台の縁までの距離"
    )
    bpy.types.Scene.keychain_main_terrain_offset = bpy.props.FloatProperty(
        name="対象県の底上げ高さ (mm)",
        default=2.0, min=0.0, max=10.0, step=10,
        description="対象の都道府県を他の県や海よりもどれだけ高く底上げするか"
    )
    bpy.types.Scene.keychain_sea_land_gap = bpy.props.FloatProperty(
        name="海・陸の隙間 (mm)",
        default=0.0, min=0.0, max=4.0, step=10,
        description="海と陸地の間に設ける隙間の幅 (アクリルが見える部分)"
    )
    bpy.types.Scene.keychain_pdf_line_width = bpy.props.FloatProperty(
        name="PDFの線の太さ (pt)",
        default=1.5, min=0.1, max=10.0, step=10,
        description="出力される県境PDFの線の太さ"
    )
    bpy.types.Scene.keychain_pdf_color_sea = bpy.props.FloatVectorProperty(
        name="海の色", subtype='COLOR', size=3,
        default=(0.0, 0.5, 1.0), min=0.0, max=1.0,
        description="PDF背景(海)の色"
    )
    bpy.types.Scene.keychain_pdf_color_land = bpy.props.FloatVectorProperty(
        name="他の陸地の色", subtype='COLOR', size=3,
        default=(0.0, 0.8, 0.0), min=0.0, max=1.0,
        description="PDFの他の陸地の色"
    )
    bpy.types.Scene.keychain_pdf_color_target = bpy.props.FloatVectorProperty(
        name="対象県の色", subtype='COLOR', size=3,
        default=(1.0, 1.0, 0.0), min=0.0, max=1.0,
        description="PDFの対象県の色"
    )
    bpy.types.Scene.keychain_resolution = bpy.props.IntProperty(
        name="解像度",
        default=200, min=50, max=500,
        description="地形メッシュの解像度 (高いほど精密)"
    )
    bpy.types.Scene.keychain_zoom = bpy.props.IntProperty(
        name="ズームレベル",
        default=10, min=8, max=14,
        description="標高タイルのズームレベル (高いほど高精度)"
    )

    bpy.utils.register_class(KEYCHAIN_PT_MainPanel)
    bpy.utils.register_class(KEYCHAIN_OT_Generate)
    bpy.utils.register_class(KEYCHAIN_OT_ExportSTL)


def unregister():
    bpy.utils.unregister_class(KEYCHAIN_OT_ExportSTL)
    bpy.utils.unregister_class(KEYCHAIN_OT_Generate)
    bpy.utils.unregister_class(KEYCHAIN_PT_MainPanel)

    del bpy.types.Scene.keychain_prefecture
    del bpy.types.Scene.keychain_exaggeration
    del bpy.types.Scene.keychain_margin_ratio
    del bpy.types.Scene.keychain_diameter
    del bpy.types.Scene.keychain_hole_diameter
    del bpy.types.Scene.keychain_hole_inner_margin
    del bpy.types.Scene.keychain_main_terrain_offset
    del bpy.types.Scene.keychain_sea_land_gap
    del bpy.types.Scene.keychain_pdf_line_width
    del bpy.types.Scene.keychain_pdf_color_sea
    del bpy.types.Scene.keychain_pdf_color_land
    del bpy.types.Scene.keychain_pdf_color_target
    del bpy.types.Scene.keychain_resolution
    del bpy.types.Scene.keychain_zoom


# ============================================================
# スクリプト直接実行用
# ============================================================

# 再実行時に既存の登録をクリア (Blender スクリプティングタブ / VSCode 両対応)
try:
    unregister()
except Exception:
    pass
register()

if __name__ == "__main__":
    pass  # 上記で登録済み

    # デフォルトで神奈川県を自動生成する場合はコメント解除:
    # gen = KeychainGenerator("神奈川県", config={
    #     'exaggeration': 2.0,
    #     'resolution': 200,
    #     'zoom': 10,
    # })
    # gen.generate()