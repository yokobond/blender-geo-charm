import bpy

from .builder import KeychainGenerator

class PREFECTURE_OT_Generate(bpy.types.Operator):
    bl_idname = "prefecture.generate"
    bl_label = "キーホルダー生成"
    bl_description = "選択した都道府県のキーホルダー3Dモデルを生成"

    def execute(self, context):
        scene = context.scene
        config = {
            'exaggeration': scene.prefecture_exaggeration,
            'margin_ratio': scene.prefecture_margin_ratio,
            'diameter_mm': scene.prefecture_diameter,
            'hole_diameter_mm': scene.prefecture_hole_diameter,
            'hole_inner_margin_mm': scene.prefecture_hole_inner_margin,
            'main_terrain_offset_mm': scene.prefecture_main_terrain_offset,
            'sea_land_gap_mm': scene.prefecture_sea_land_gap,
            'pdf_line_width_pt': scene.prefecture_pdf_line_width,
            'pdf_color_sea': tuple(list(scene.prefecture_pdf_color_sea) + [1.0]),
            'pdf_color_land': tuple(list(scene.prefecture_pdf_color_land) + [1.0]),
            'pdf_color_target': tuple(list(scene.prefecture_pdf_color_target) + [1.0]),
            'resolution': scene.prefecture_resolution,
            'zoom': scene.prefecture_zoom,
        }

        try:
            gen = KeychainGenerator(
                prefecture_name=scene.prefecture_prefecture,
                config=config
            )
            gen.generate()
            self.report({'INFO'}, f"{scene.prefecture_prefecture}のキーホルダーを生成しました")
        except Exception as e:
            self.report({'ERROR'}, f"生成エラー: {str(e)}")
            import traceback
            traceback.print_exc()

        return {'FINISHED'}

class PREFECTURE_OT_ExportSTL(bpy.types.Operator):
    bl_idname = "prefecture.export_stl"
    bl_label = "STL エクスポート"
    bl_description = "生成したモデルをSTLファイルにエクスポート"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        self.filepath = f"keychain_{context.scene.prefecture_prefecture}.stl"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        config = {
            'exaggeration': scene.prefecture_exaggeration,
            'margin_ratio': scene.prefecture_margin_ratio,
            'diameter_mm': scene.prefecture_diameter,
            'hole_diameter_mm': scene.prefecture_hole_diameter,
            'hole_inner_margin_mm': scene.prefecture_hole_inner_margin,
            'main_terrain_offset_mm': scene.prefecture_main_terrain_offset,
            'sea_land_gap_mm': scene.prefecture_sea_land_gap,
            'pdf_line_width_pt': scene.prefecture_pdf_line_width,
            'pdf_color_sea': tuple(list(scene.prefecture_pdf_color_sea) + [1.0]),
            'pdf_color_land': tuple(list(scene.prefecture_pdf_color_land) + [1.0]),
            'pdf_color_target': tuple(list(scene.prefecture_pdf_color_target) + [1.0]),
            'resolution': scene.prefecture_resolution,
            'zoom': scene.prefecture_zoom,
        }
        gen = KeychainGenerator(scene.prefecture_prefecture, config=config)
        gen.export_stl(self.filepath)
        self.report({'INFO'}, f"STL エクスポート完了: {self.filepath}")
        return {'FINISHED'}