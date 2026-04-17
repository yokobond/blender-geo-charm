# Prefecture Charm - Blender Extension Add-on
# 国土地理院の標高タイルと都道府県境界GeoJSONを使用し、
# 都道府県の地形を再現した円形キーホルダー3Dモデルを生成する。

bl_info = {
    "name": "Prefecture Charm",
    "author": "Koji Yokokawa",
    "description": "国土地理院の標高データから都道府県キーホルダー3Dモデルを生成",
    "blender": (4, 2, 0),
    "version": (1, 0, 0),
    "location": "View3D > Sidebar > キーホルダー",
    "warning": "",
    "category": "Object",
}

from . import auto_load

# auto_load はアドオン内の全クラスを自動検出して登録・解除する
auto_load.init()


def register():
    auto_load.register()


def unregister():
    auto_load.unregister()
