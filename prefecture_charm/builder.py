import bpy
import bmesh
import math
import os
import numpy as np

from .utils import ElevationFetcher, PrefectureBoundary, SHAPELY_AVAILABLE
from .constants import (
    DEFAULT_KEYCHAIN_DIAMETER_MM,
    DEFAULT_BASE_THICKNESS_MM,
    DEFAULT_TERRAIN_MAX_HEIGHT_MM,
    DEFAULT_HOLE_DIAMETER_MM,
    DEFAULT_NEIGHBOR_THICKNESS_MM,
    DEFAULT_ISLAND_OFFSET_MM,
    DEFAULT_MAIN_TERRAIN_OFFSET_MM,
    DEFAULT_ZOOM_LEVEL,
    DEFAULT_MAP_MARGIN_RATIO
)

class KeychainModelBuilder:

    def __init__(self, config=None):
        self.config = config or {}
        self.diameter_mm = self.config.get('diameter_mm', DEFAULT_KEYCHAIN_DIAMETER_MM)
        self.base_thickness = self.config.get('base_thickness_mm', DEFAULT_BASE_THICKNESS_MM)
        self.terrain_max_height = self.config.get('terrain_max_height_mm', DEFAULT_TERRAIN_MAX_HEIGHT_MM)
        self.hole_diameter = self.config.get('hole_diameter_mm', DEFAULT_HOLE_DIAMETER_MM)

        hole_inner_margin = self.config.get('hole_inner_margin_mm', 1.0)
        self.hole_margin = hole_inner_margin + (self.hole_diameter / 2.0)

        self.neighbor_thickness = self.config.get('neighbor_thickness_mm', DEFAULT_NEIGHBOR_THICKNESS_MM)
        self.island_offset = self.config.get('island_offset_mm', DEFAULT_ISLAND_OFFSET_MM)
        self.main_terrain_offset = self.config.get('main_terrain_offset_mm', DEFAULT_MAIN_TERRAIN_OFFSET_MM)
        self.exaggeration = self.config.get('exaggeration', 2.0)

        self.scale_factor = 0.001
        self.ground_size_m = 0.0

    def clear_scene(self):
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)

        for col in bpy.data.collections:
            if col.name.startswith("Keychain"):
                bpy.data.collections.remove(col)

    def _create_collection(self, name):
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
        return col

    def build_circular_base(self, collection):
        sf = self.scale_factor
        radius = self.diameter_mm / 2.0 * sf
        thickness = self.base_thickness * sf
        hole_r = self.hole_diameter / 2.0 * sf
        hole_center_offset = radius - self.hole_margin * sf

        base_center_z = -thickness / 2

        bpy.ops.mesh.primitive_cylinder_add(
            radius=radius,
            depth=thickness,
            location=(0, 0, base_center_z),
            vertices=128
        )
        base = bpy.context.active_object
        base.name = "Base_Acrylic"

        bpy.ops.mesh.primitive_cylinder_add(
            radius=hole_r,
            depth=thickness * 10,
            location=(0, hole_center_offset, 0),
            vertices=64
        )
        hole = bpy.context.active_object
        hole.name = "Keychain_Hole_Cutter"
        hole.display_type = 'WIRE'
        hole.hide_render = True
        self.hole_cutter = hole

        bool_mod = base.modifiers.new(name="Hole", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = hole
        for solver_name in ('EXACT', 'FLOAT', 'FAST'):
            try:
                bool_mod.solver = solver_name
                break
            except TypeError:
                continue

        for c in hole.users_collection:
            c.objects.unlink(hole)
        collection.objects.link(hole)

        mat = bpy.data.materials.new(name="Acrylic_Clear")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        output = nodes.new('ShaderNodeOutputMaterial')
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = (0.95, 0.97, 1.0, 1.0)
        bsdf.inputs['Alpha'].default_value = 0.15
        bsdf.inputs['Roughness'].default_value = 0.05
        bsdf.inputs['IOR'].default_value = 1.49
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

        for c in base.users_collection:
            c.objects.unlink(base)
        collection.objects.link(base)

        return base

    def build_terrain_mesh(self, elevations, mask, collection,
                           name="Terrain_Main", height_scale=None,
                           material_color=(0.4, 0.35, 0.28, 1.0),
                           z_offset_mm=0.0):
        sf = self.scale_factor
        radius = self.diameter_mm / 2.0 * sf
        resolution = elevations.shape[0]

        masked_vals = elevations[mask > 0.5]
        if masked_vals.size > 0 and masked_vals.max() > 0:
            elev_max = float(np.percentile(masked_vals, 95))
            elevations = np.clip(elevations, 0.0, elev_max * 1.5)
        else:
            elev_max = float(elevations.max())
        if elev_max <= 0:
            elev_max = 1.0

        if height_scale is None:
            if hasattr(self, 'ground_size_m') and self.ground_size_m > 0:
                height_scale = (self.diameter_mm * sf / self.ground_size_m) * self.exaggeration
            else:
                height_scale = self.terrain_max_height * sf * self.exaggeration / elev_max

        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)

        bm = bmesh.new()

        verts = {}
        for iy in range(resolution):
            for ix in range(resolution):
                nx = (ix / (resolution - 1)) * 2.0 - 1.0
                ny = (iy / (resolution - 1)) * 2.0 - 1.0

                dist = math.sqrt(nx * nx + ny * ny)
                if dist > 1.0:
                    continue

                if mask[iy, ix] < 0.5:
                    continue

                x = nx * radius
                y = -ny * radius
                z = (z_offset_mm * sf) + elevations[iy, ix] * height_scale

                v = bm.verts.new((x, y, z))
                verts[(ix, iy)] = v

        bm.verts.ensure_lookup_table()

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

        self._add_solid_bottom(obj, target_z=0.0)

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
        color = self.config.get('pdf_color_land', (0.1, 0.8, 0.2, 1.0))
        flat_elevations = np.full_like(elevations, 0.5)
        return self.build_terrain_mesh(
            flat_elevations, mask, collection,
            name="Other_Land_Engraving",
            height_scale=self.scale_factor,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

    def build_sea_indication(self, elevations, sea_mask, collection, z_offset_mm=0.0):
        sf = self.scale_factor
        color = self.config.get('pdf_color_sea', (0.0, 0.5, 1.0, 1.0))
        flat_sea = np.full_like(elevations, 0.5)
        return self.build_terrain_mesh(
            flat_sea, sea_mask, collection,
            name="Sea_Surface",
            height_scale=sf,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

    def build_island_piece(self, elevations, island_mask, collection, island_idx=0, z_offset_mm=0.0):
        name = f"Island_{island_idx}"
        color = self.config.get('pdf_color_target', (1.0, 0.8, 0.0, 1.0))
        obj = self.build_terrain_mesh(
            elevations, island_mask, collection,
            name=name,
            material_color=color,
            z_offset_mm=z_offset_mm
        )

        return obj

    def _add_solid_bottom(self, obj, target_z=0.0):
        if not obj.data.vertices:
            return

        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(obj.data)

        if not bm.faces:
            bpy.ops.object.mode_set(mode='OBJECT')
            return

        extrude_res = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])

        new_verts = [e for e in extrude_res['geom'] if isinstance(e, bmesh.types.BMVert)]
        new_faces = [e for e in extrude_res['geom'] if isinstance(e, bmesh.types.BMFace)]
        for v in new_verts:
            v.co.z = target_z

        bmesh.ops.reverse_faces(bm, faces=new_faces)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        bmesh.update_edit_mesh(obj.data)
        bpy.ops.object.mode_set(mode='OBJECT')

    def add_keychain_ring_preview(self, collection):
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

class KeychainGenerator:

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

    def _compute_bounds(self):
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
            margin = 0.15 * (self.margin_ratio / 0.3)
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

        return lon_min, lat_min, lon_max, lat_max, span

    def generate(self):
        print(f"\n{'='*60}")
        print(f"  キーホルダー生成: {self.prefecture_name}")
        print(f"  標高誇張: {self.exaggeration}倍")
        print(f"  解像度: {self.resolution}x{self.resolution}")
        print(f"{'='*60}\n")

        print("[1/7] シーンをクリア中...")
        self.builder.clear_scene()

        print("[2/7] 県境データを取得中...")
        try:
            self.boundary.load_from_url()
        except Exception as e:
            print(f"  県境データ取得失敗: {e}")
            print("  → 矩形範囲で代替します")

        print("[3/7] 対象県の範囲を計算中...")
        lon_min, lat_min, lon_max, lat_max, span = self._compute_bounds()

        self.builder.ground_size_m = span * 111000

        print(f"  範囲: lat=[{lat_min:.4f}, {lat_max:.4f}], lon=[{lon_min:.4f}, {lon_max:.4f}]")

        print("[4/7] 標高データを取得中...")
        elevations = self.fetcher.get_elevation_grid(
            lat_min, lat_max, lon_min, lon_max,
            resolution=self.resolution
        )
        print(f"  標高範囲: {elevations.min():.1f}m 〜 {elevations.max():.1f}m")

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
            sea_mask = np.ones_like(main_mask)
            sea_mask[main_mask > 0.5] = 0
            sea_mask[other_land_mask > 0.5] = 0

            gap_mm = self.config.get('sea_land_gap_mm', 0.0)
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

            sea_mask = _erode(sea_mask, gap_px)

            for iy in range(self.resolution):
                for ix in range(self.resolution):
                    nx = (ix / (self.resolution - 1)) * 2.0 - 1.0
                    ny = (iy / (self.resolution - 1)) * 2.0 - 1.0
                    if nx*nx + ny*ny > 1.0:
                        sea_mask[iy, ix] = 0
                        other_land_mask[iy, ix] = 0
        else:
            main_mask = np.ones((self.resolution, self.resolution), dtype=np.float32)
            other_land_mask = np.zeros_like(main_mask)
            sea_mask = np.zeros_like(main_mask)

        print("[6/7] 3Dモデルを構築中...")
        col = self.builder._create_collection(f"Keychain_{self.prefecture_name}")

        print("  → 円形土台...")
        base = self.builder.build_circular_base(col)

        main_terrain_offset_value = self.config.get('main_terrain_offset_mm', DEFAULT_MAIN_TERRAIN_OFFSET_MM)

        base_z_offset = 0.0
        main_z_offset = base_z_offset + main_terrain_offset_value

        print("  → メイン地形...")
        color_target = self.config.get('pdf_color_target', (1.0, 0.8, 0.0, 1.0))
        terrain = self.builder.build_terrain_mesh(elevations, main_mask, col, z_offset_mm=main_z_offset, material_color=color_target)

        if other_land_mask.max() > 0:
            print("  → 他の陸地の表示...")
            self.builder.build_other_land_engraving(elevations, other_land_mask, col, z_offset_mm=base_z_offset)

        if sea_mask.max() > 0:
            print("  → 海の表示...")
            self.builder.build_sea_indication(elevations, sea_mask, col, z_offset_mm=base_z_offset)

        if SHAPELY_AVAILABLE and self.boundary.features:
            main_poly, islands = self.boundary.detect_islands(self.prefecture_name)
            if islands:
                print(f"  → {len(islands)}個の島パーツを分離...")
                for idx, island_poly in enumerate(islands):
                    island_mask = self.boundary._rasterize(
                        island_poly, self.resolution,
                        lon_min, lat_min, lon_max, lat_max,
                    )
                    if island_mask.max() > 0:
                        self.builder.build_island_piece(
                            elevations, island_mask, col, island_idx=idx, z_offset_mm=main_z_offset
                        )

        self.builder.add_keychain_ring_preview(col)

        print("[7/7] ビューを設定中...")
        self._setup_viewport()

        print(f"\n{'='*60}")
        print(f"  完成！ コレクション '{col.name}' に生成されました")
        print(f"  STL エクスポート: ファイル → エクスポート → STL")
        print(f"  出典: 国土地理院 地理院タイル")
        print(f"{'='*60}\n")

        return col

    def _setup_viewport(self):
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

    def _export_cut_svg(self, svg_path, lon_min, lat_min, lon_max, lat_max):
        d_mm = self.builder.diameter_mm
        w_mm, h_mm = d_mm, d_mm

        sx = w_mm / (lon_max - lon_min)
        sy = h_mm / (lat_max - lat_min)

        def proj_x(lon):
            return (lon - lon_min) * sx

        def proj_y(lat):
            return (lat_max - lat) * sy

        parts = []

        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w_mm:.3f} {h_mm:.3f}" width="{w_mm}mm" height="{h_mm}mm">')
        style = 'fill="none" stroke="red" stroke-width="0.5"'

        if SHAPELY_AVAILABLE:
            poly = self.boundary.get_prefecture_polygon(self.prefecture_name)

            def add_polygon(p):
                path_data = []
                coords = list(p.exterior.coords)
                for i, (lon, lat) in enumerate(coords):
                    cmd = "M" if i == 0 else "L"
                    path_data.append(f"{cmd} {proj_x(lon):.3f} {proj_y(lat):.3f}")
                path_data.append("Z")

                for interior in p.interiors:
                    icoords = list(interior.coords)
                    for i, (lon, lat) in enumerate(icoords):
                        cmd = "M" if i == 0 else "L"
                        path_data.append(f"{cmd} {proj_x(lon):.3f} {proj_y(lat):.3f}")
                    path_data.append("Z")

                d_str = " ".join(path_data)
                parts.append(f'  <path d="{d_str}" {style} />')

            if poly:
                from shapely.geometry import Polygon as _Polygon, MultiPolygon as _MultiPolygon
                if isinstance(poly, _Polygon):
                    add_polygon(poly)
                elif isinstance(poly, _MultiPolygon):
                    for geom in poly.geoms:
                        add_polygon(geom)

        rad = d_mm / 2.0
        parts.append(f'  <circle cx="{rad:.3f}" cy="{rad:.3f}" r="{rad:.3f}" {style} />')

        hole_r = self.builder.hole_diameter / 2.0
        hole_cy = rad - (rad - self.builder.hole_margin)
        parts.append(f'  <circle cx="{rad:.3f}" cy="{hole_cy:.3f}" r="{hole_r:.3f}" {style} />')

        parts.append('</svg>')

        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(parts))

    def export_stl(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(
                os.path.expanduser("~"),
                f"keychain_{self.prefecture_name}.stl"
            )

        if os.path.isdir(filepath):
            filepath = os.path.join(filepath, f"keychain_{self.prefecture_name}.stl")
        elif not filepath.lower().endswith(".stl"):
            filepath += ".stl"

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

        output_dir = os.path.dirname(filepath)

        try:
            self.boundary.load_from_url()
        except Exception:
            pass

        lon_min, lat_min, lon_max, lat_max, _ = self._compute_bounds()

        print(f"  → 土台用SVGを {output_dir} にエクスポート中...")
        try:
            svg_filename = f"{self.prefecture_name}_cut.svg"
            svg_path = os.path.join(output_dir, svg_filename)
            self._export_cut_svg(svg_path, lon_min, lat_min, lon_max, lat_max)
            print(f"  → SVG出力完了: {svg_path}")
        except Exception as e:
            print(f"  → SVG出力エラー: {e}")

        print(f"  → 土台用PDFを {output_dir} にエクスポート中...")
        try:
            from . import export_prefecture_pdf as _pdf_mod
            pdf_path = _pdf_mod.export_prefecture_pdf(
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
        except Exception as e:
            print(f"  → PDF出力エラー: {e}")
