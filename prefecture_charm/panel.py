import bpy

class PREFECTURE_PT_MainPanel(bpy.types.Panel):
    bl_label = "キーホルダー生成"
    bl_idname = "PREFECTURE_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "キーホルダー"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="都道府県キーホルダー生成", icon='MESH_DATA')
        layout.separator()

        layout.prop(scene, "prefecture_prefecture", text="都道府県")

        box = layout.box()
        box.label(text="パラメータ", icon='PREFERENCES')
        box.prop(scene, "prefecture_exaggeration", text="標高誇張倍率")
        box.prop(scene, "prefecture_margin_ratio", text="マージン比率")
        box.prop(scene, "prefecture_diameter", text="直径 (mm)")
        box.prop(scene, "prefecture_pdf_color_sea", text="海の色")
        box.prop(scene, "prefecture_pdf_color_land", text="他の陸地の色")
        box.prop(scene, "prefecture_pdf_color_target", text="対象県の色")
        box.prop(scene, "prefecture_hole_inner_margin", text="穴の内側マージン (mm)")
        box.prop(scene, "prefecture_main_terrain_offset", text="対象県の底上げ高さ (mm)")
        box.prop(scene, "prefecture_sea_land_gap", text="海と陸の隙間 (mm)")
        box.prop(scene, "prefecture_pdf_line_width", text="PDFの線の太さ (pt)")
        box.prop(scene, "prefecture_resolution", text="解像度")
        box.prop(scene, "prefecture_zoom", text="タイルズームレベル")

        layout.separator()

        layout.operator("prefecture.generate", text="キーホルダーを生成", icon='PLAY')
        layout.operator("prefecture.export_stl", text="STL エクスポート", icon='EXPORT')
