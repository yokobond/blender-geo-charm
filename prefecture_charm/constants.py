# constants.py - アドオン全体で使用する定数定義
# 外部データソースのURLとデフォルトパラメータをまとめて管理する。

import math

# 国土地理院 標高タイル (XYZ形式) の URL テンプレート
# dem: 標高メッシュデータ、dem5a: より高精度な5mメッシュデータ
GSI_DEM_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt"
GSI_DEM5A_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem5a/{z}/{x}/{y}.txt"

# 都道府県の境界ポリゴンを含む GeoJSON のURL
PREFECTURES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/dataofjapan/land/master/japan.geojson"
)

# キーホルダーの形状に関するデフォルト値 (単位: mm)
DEFAULT_KEYCHAIN_DIAMETER_MM = 50.0     # 円形土台の直径
DEFAULT_BASE_THICKNESS_MM = 2.0         # アクリル土台の厚さ
DEFAULT_TERRAIN_MAX_HEIGHT_MM = 8.0     # 地形の最大高さ
DEFAULT_HOLE_DIAMETER_MM = 4.0          # キーリング穴の直径
DEFAULT_HOLE_MARGIN_MM = 3.0            # 穴の中心から土台端までのマージン
DEFAULT_NEIGHBOR_THICKNESS_MM = 0.5    # 隣接県の厚さ
DEFAULT_ISLAND_OFFSET_MM = 0.3          # 島の底上げ量
DEFAULT_MAIN_TERRAIN_OFFSET_MM = 2.0   # 対象県の底上げ量（他の陸地・海より高くする）
DEFAULT_BORDER_GROOVE_DEPTH_MM = 1.0   # 県境溝の深さ
DEFAULT_MAP_MARGIN_RATIO = 0.3          # 地図の余白の比率（県域に対する割合）
DEFAULT_ZOOM_LEVEL = 10                  # 標高タイル取得時のデフォルトズームレベル

# 都道府県コード→名称のマッピング (JIS X 0401 準拠)
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
