# utils.py - 標高データ取得・県境ポリゴン管理のユーティリティ
# ElevationFetcher: 国土地理院タイルから標高グリッドを構築する
# PrefectureBoundary: GeoJSON から都道府県ポリゴンを管理し、マスク生成を行う

import math
import os
import json
import tempfile
import numpy as np
import requests

from shapely.geometry import shape, MultiPolygon
SHAPELY_AVAILABLE = True

from .constants import GSI_DEM_URL, GSI_DEM5A_URL, PREFECTURES_GEOJSON_URL, DEFAULT_ZOOM_LEVEL


def latlon_to_tile(lat, lon, zoom):
    """緯度経度をWebメルカトル (XYZ) タイル座標に変換する。"""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_to_latlon(x, y, zoom):
    """XYZ タイル座標の左上隅の緯度経度を返す。"""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def tile_bounds(x, y, zoom):
    """XYZ タイルの地理的バウンディングボックス (lat_max, lon_min, lat_min, lon_max) を返す。"""
    lat_max, lon_min = tile_to_latlon(x, y, zoom)
    lat_min, lon_max = tile_to_latlon(x + 1, y + 1, zoom)
    return lat_max, lon_min, lat_min, lon_max


class ElevationFetcher:
    """国土地理院の標高タイルを取得し、指定範囲の標高グリッドを生成するクラス。

    タイルデータはファイルシステムとメモリの2段キャッシュで管理し、
    同一タイルの重複ダウンロードを防ぐ。
    """

    def __init__(self, zoom=DEFAULT_ZOOM_LEVEL, use_dem5a=False, cache_dir=None):
        self.zoom = zoom
        self.base_url = GSI_DEM5A_URL if use_dem5a else GSI_DEM_URL
        self.cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "gsi_dem_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._tile_cache = {}  # メモリキャッシュ: {(tx, ty, zoom): ndarray}

    def _fetch_tile(self, tx, ty):
        """単一タイルの標高データ (256x256 ndarray) を取得する。

        メモリキャッシュ → ファイルキャッシュ → HTTP の順で参照し、
        海や欠損値 ('e') は 0.0m に、異常値 (<-100m, >8000m) もクリップする。
        タイルが存在しない場合 (404) やネットワーク障害時はゼロ配列を返す。
        """
        cache_key = (tx, ty, self.zoom)
        if cache_key in self._tile_cache:
            return self._tile_cache[cache_key]

        cache_file = os.path.join(self.cache_dir, f"dem_{self.zoom}_{tx}_{ty}.npy")
        if os.path.exists(cache_file):
            data = np.load(cache_file)
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
                # 海域など標高データが存在しないタイルはゼロで埋める
                data = np.zeros((256, 256), dtype=np.float32)
                self._tile_cache[cache_key] = data
                return data
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  WARNING: タイル取得失敗 ({url}): {e}")
            data = np.zeros((256, 256), dtype=np.float32)
            self._tile_cache[cache_key] = data
            return data

        # CSV テキスト形式のタイルデータをパース (256行×256列)
        data = np.zeros((256, 256), dtype=np.float32)
        lines = resp.text.strip().split('\n')
        for row_idx, line in enumerate(lines[:256]):
            values = line.split(',')
            for col_idx, val in enumerate(values[:256]):
                val = val.strip()
                if val == 'e' or val == '':
                    data[row_idx, col_idx] = 0.0
                else:
                    try:
                        data[row_idx, col_idx] = float(val)
                    except ValueError:
                        data[row_idx, col_idx] = 0.0

        data[data < -100] = 0.0
        data[data > 8000] = 0.0
        data = np.maximum(data, 0.0)

        np.save(cache_file, data)
        self._tile_cache[cache_key] = data
        return data

    def get_elevation_grid(self, lat_min, lat_max, lon_min, lon_max, resolution=256):
        """指定した地理範囲の標高グリッドを resolution×resolution で返す。

        必要なタイルを全て取得して結合し、要求範囲をクロップした後、
        線形補間で resolution にリサンプリングする。
        """
        tx_min, ty_max = latlon_to_tile(lat_min, lon_min, self.zoom)
        tx_max, ty_min = latlon_to_tile(lat_max, lon_max, self.zoom)

        tx_min -= 1
        ty_min -= 1
        tx_max += 1
        ty_max += 1

        print(f"標高データ取得: タイル範囲 x=[{tx_min}..{tx_max}], y=[{ty_min}..{ty_max}]")
        num_tiles_x = tx_max - tx_min + 1
        num_tiles_y = ty_max - ty_min + 1
        total_px_x = num_tiles_x * 256
        total_px_y = num_tiles_y * 256

        full_grid = np.zeros((total_px_y, total_px_x), dtype=np.float32)
        for ty in range(ty_min, ty_max + 1):
            for tx in range(tx_min, tx_max + 1):
                tile_data = self._fetch_tile(tx, ty)
                iy = (ty - ty_min) * 256
                ix = (tx - tx_min) * 256
                full_grid[iy:iy+256, ix:ix+256] = tile_data

        actual_lat_max, actual_lon_min = tile_to_latlon(tx_min, ty_min, self.zoom)
        actual_lat_min, actual_lon_max = tile_to_latlon(tx_max + 1, ty_max + 1, self.zoom)

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

        rows_resampled = np.zeros((resolution, cropped.shape[1]), dtype=np.float32)
        src_rows = np.linspace(0, cropped.shape[0] - 1, resolution)
        for c in range(cropped.shape[1]):
            rows_resampled[:, c] = np.interp(src_rows, np.arange(cropped.shape[0]), cropped[:, c])

        result = np.zeros((resolution, resolution), dtype=np.float32)
        src_cols = np.linspace(0, rows_resampled.shape[1] - 1, resolution)
        for r in range(resolution):
            result[r, :] = np.interp(src_cols, np.arange(rows_resampled.shape[1]), rows_resampled[r, :])

        return result


class PrefectureBoundary:
    """都道府県の境界ポリゴンを管理し、マスク生成や隣接県検索を行うクラス。

    GeoJSON データを URL またはファイルから読み込み、Shapely ジオメトリとして保持する。
    create_mask() で各都道府県の領域を 0/1 ラスタマスクに変換できる。
    """

    def __init__(self, geojson_path=None):
        self.features = {}          # {県名: {geometry, properties}}
        self._geojson_data = None
        self._geojson_path = geojson_path

    def load_from_url(self, url=PREFECTURES_GEOJSON_URL):
        """GeoJSON をキャッシュ付きで URL から読み込む。"""
        cache_file = os.path.join(tempfile.gettempdir(), "japan_prefectures.geojson")
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
        """ローカルの GeoJSON ファイルから読み込む。"""
        with open(filepath, 'r', encoding='utf-8') as f:
            self._geojson_data = json.load(f)
        self._parse_features()

    def _parse_features(self):
        """GeoJSON の features 配列を解析し self.features に格納する。"""
        if not SHAPELY_AVAILABLE:
            print("WARNING: shapely がないため県境ポリゴンの解析をスキップ")
            return

        for feat in self._geojson_data.get('features', []):
            props = feat.get('properties', {})
            name = props.get('nam_ja') or props.get('N03_001') or props.get('name')
            if name:
                geom = shape(feat['geometry'])
                self.features[name] = {
                    'geometry': geom,
                    'properties': props,
                }

    def get_prefecture_polygon(self, name):
        """県名でポリゴンを検索する。完全一致 → 部分一致の順で照合する。"""
        if name in self.features:
            return self.features[name]['geometry']
        for key, val in self.features.items():
            if name in key or key in name:
                return val['geometry']
        return None

    def get_neighbor_prefectures(self, target_name, buffer_deg=0.1):
        """対象県を buffer_deg だけ膨らませた領域と交差する隣接県名のリストを返す。"""
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
        """県のバウンディングボックス (minx, miny, maxx, maxy) を返す。見つからない場合は None。"""
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return None
        return poly.bounds

    @staticmethod
    def _rasterize(geom, resolution, lon_min, lat_min, lon_max, lat_max) -> np.ndarray:
        """Shapely ジオメトリを resolution × resolution の 0/1 マスク配列に変換する。

        shapely.vectorized が利用可能な場合はベクトル化処理で高速化する。
        利用できない場合は Point ベースのフォールバック実装を使用する。
        """
        try:
            from shapely.vectorized import contains as vec_contains
        except ImportError:
            from shapely.prepared import prep
            from shapely.geometry import Point as _Point
            prepared = prep(geom)
            lons = np.linspace(lon_min, lon_max, resolution)
            lats = np.linspace(lat_max, lat_min, resolution)
            mask = np.zeros((resolution, resolution), dtype=np.float32)
            for iy, lat in enumerate(lats):
                for ix, lon in enumerate(lons):
                    if prepared.contains(_Point(lon, lat)):
                        mask[iy, ix] = 1.0
            return mask

        lons = np.linspace(lon_min, lon_max, resolution)
        lats = np.linspace(lat_max, lat_min, resolution)
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        inside = vec_contains(geom, lon_grid.ravel(), lat_grid.ravel())
        return inside.reshape(resolution, resolution).astype(np.float32)

    def create_mask(self, name, resolution, lon_min, lat_min, lon_max, lat_max):
        """指定県の領域マスクを生成する。県が見つからない場合は全面1のマスクを返す。"""
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return np.ones((resolution, resolution), dtype=np.float32)
        return self._rasterize(poly, resolution, lon_min, lat_min, lon_max, lat_max)

    def create_other_land_mask(self, target_name, resolution, lon_min, lat_min, lon_max, lat_max):
        """対象県以外の全陸地を合成したマスクを生成する。隣接県・遠隔地問わず全て含む。"""
        from shapely.ops import unary_union
        other_union = unary_union([
            data['geometry'] for name, data in self.features.items()
            if name != target_name and name not in target_name and target_name not in name
        ])
        return self._rasterize(other_union, resolution, lon_min, lat_min, lon_max, lat_max)

    def detect_islands(self, name):
        """県のポリゴンを本土と島嶼部に分離する。

        MultiPolygon の場合、最大面積のポリゴンを本土とし、
        本土の 0.1% 以上の面積を持つ残りのポリゴンを島として返す。
        Returns:
            (main_polygon, [island_polygon, ...])
        """
        poly = self.get_prefecture_polygon(name)
        if poly is None:
            return None, []

        if isinstance(poly, MultiPolygon):
            parts = list(poly.geoms)
            parts.sort(key=lambda p: p.area, reverse=True)
            main = parts[0]
            islands = parts[1:]
            # 本土面積の 0.1% 未満の小島は省略する
            islands = [isl for isl in islands if isl.area > main.area * 0.001]
            return main, islands
        else:
            return poly, []