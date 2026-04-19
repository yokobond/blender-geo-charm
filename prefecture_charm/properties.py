# properties.py - Blender シーンプロパティの登録・解除
# UI パネルで操作するパラメータを bpy.types.Scene に動的に追加する。
# アドオン有効化時に register()、無効化時に unregister() が呼ばれる。

import bpy

from .constants import PREFECTURE_NAMES

# EnumProperty 用の選択肢リスト: (識別子, 表示名, 説明)
PREFECTURE_ITEMS = [(name, name, "") for code, name in sorted(PREFECTURE_NAMES.items())]

def register():
    """アドオン有効化時に全シーンプロパティを bpy.types.Scene に登録する。"""
    bpy.types.Scene.prefecture_prefecture = bpy.props.EnumProperty(
        name="都道府県",
        items=PREFECTURE_ITEMS,
        default="神奈川県"
    )
    bpy.types.Scene.prefecture_exaggeration = bpy.props.FloatProperty(
        name="標高誇張倍率",
        default=3.0, min=1.0, max=10.0, step=10,
        description="標高の誇張倍率 (1.0=実スケール, 3.0=3倍)"
    )
    bpy.types.Scene.prefecture_margin_ratio = bpy.props.FloatProperty(
        name="マージン比率",
        default=0.1, min=0.0, max=1.0, step=5,
        description="周辺の余白の広さ (0.0で余白なし)"
    )
    bpy.types.Scene.prefecture_diameter = bpy.props.FloatProperty(
        name="直径 (mm)",
        default=50.0, min=30.0, max=100.0, step=100,
        description="円形土台の直径"
    )
    bpy.types.Scene.prefecture_hole_diameter = bpy.props.FloatProperty(
        name="穴の直径 (mm)",
        default=4.0, min=1.0, max=20.0, step=100,
        description="キーホルダーを通す穴の直径"
    )
    bpy.types.Scene.prefecture_hole_inner_margin = bpy.props.FloatProperty(
        name="穴の内側マージン (mm)",
        default=1.0, min=0.0, max=10.0, step=10,
        description="リング穴の内側の端から土台の縁までの距離"
    )
    bpy.types.Scene.prefecture_main_terrain_offset = bpy.props.FloatProperty(
        name="対象県の底上げ高さ (mm)",
        default=2.0, min=0.0, max=10.0, step=10,
        description="対象の都道府県を他の県や海よりもどれだけ高く底上げするか"
    )
    bpy.types.Scene.prefecture_sea_land_gap = bpy.props.FloatProperty(
        name="海・陸の隙間 (mm)",
        default=0.0, min=0.0, max=4.0, step=10,
        description="海と陸地の間に設ける隙間の幅 (アクリルが見える部分)"
    )
    bpy.types.Scene.prefecture_pdf_line_width = bpy.props.FloatProperty(
        name="PDFの線の太さ (pt)",
        default=0.0, min=0.0, max=10.0, step=10,
        description="出力される県境PDFの線の太さ"
    )
    bpy.types.Scene.prefecture_pdf_color_sea = bpy.props.FloatVectorProperty(
        name="海の色", subtype='COLOR', size=3,
        default=(0.0, 0.5, 1.0), min=0.0, max=1.0,
        description="PDF背景(海)の色"
    )
    bpy.types.Scene.prefecture_pdf_color_land = bpy.props.FloatVectorProperty(
        name="他の陸地の色", subtype='COLOR', size=3,
        default=(0.0, 0.8, 0.0), min=0.0, max=1.0,
        description="PDFの他の陸地の色"
    )
    bpy.types.Scene.prefecture_pdf_color_target = bpy.props.FloatVectorProperty(
        name="対象県の色", subtype='COLOR', size=3,
        default=(1.0, 1.0, 0.0), min=0.0, max=1.0,
        description="PDFの対象県の色"
    )
    bpy.types.Scene.prefecture_resolution = bpy.props.IntProperty(
        name="解像度",
        default=200, min=50, max=500,
        description="地形メッシュの解像度 (高いほど精密)"
    )
    bpy.types.Scene.prefecture_zoom = bpy.props.IntProperty(
        name="ズームレベル",
        default=10, min=8, max=14,
        description="標高タイルのズームレベル (高いほど高精度)"
    )

def unregister():
    """アドオン無効化時に全シーンプロパティを bpy.types.Scene から削除する。"""
    # アドオン解除時にシーンプロパティを全て削除する
    for prop in [
        "prefecture_prefecture", "prefecture_exaggeration", "prefecture_margin_ratio",
        "prefecture_diameter", "prefecture_hole_diameter", "prefecture_hole_inner_margin",
        "prefecture_main_terrain_offset", "prefecture_sea_land_gap", "prefecture_pdf_line_width",
        "prefecture_pdf_color_sea", "prefecture_pdf_color_land", "prefecture_pdf_color_target",
        "prefecture_resolution", "prefecture_zoom",
    ]:
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
