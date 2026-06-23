#!/usr/bin/env python3
"""
Blend to USD Converter (with texture baking)

将 Blender .blend 文件转换为 USD (.usdc / .usda / .usd) 格式。
支持纹理烘焙：将 Infinigen 的程序化材质节点烘焙为纹理贴图，解决 USD 中家具灰色问题。

用法:
    conda activate infinigen

    # 带纹理烘焙的转换（推荐，解决灰色问题）
    python blend2usd.py input.blend -o output.usdc --bake-textures

    # 不烘焙，直接导出（家具可能是灰色）
    python blend2usd.py input.blend -o output.usdc

    # 指定烘焙分辨率
    python blend2usd.py input.blend -o output.usdc --bake-textures --bake-resolution 2048

    # 批量转换
    python blend2usd.py ./blend_files/ -o ./usd_output/ --batch --bake-textures

    # 导出动画
    python blend2usd.py input.blend -o output.usdc --bake-textures --export-animation
"""

import argparse
import logging
import os
import sys
import glob
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Bake types mapping: bake_type -> Principled BSDF input name
BAKE_TYPES = {
    "DIFFUSE": "Base Color",
    "ROUGHNESS": "Roughness",
    "NORMAL": "Normal",
}
SPECIAL_BAKE = {"METAL": "Metallic", "TRANSMISSION": "Transmission Weight"}
ALL_BAKE = BAKE_TYPES | SPECIAL_BAKE


# ─── Texture Baking Functions (adapted from infinigen/tools/export.py) ───


def uv_unwrap(obj):
    """Create a new UV layer and smart-project unwrap for baking"""
    import bpy

    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    obj.data.uv_layers.new(name="ExportUV")
    bpy.context.object.data.uv_layers["ExportUV"].active = True

    logger.info("UV Unwrapping")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    try:
        bpy.ops.uv.smart_project(angle_limit=0.7)
    except RuntimeError:
        logger.info("UV Unwrap failed, skipping mesh")
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)
        return False
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return True


def apply_all_modifiers(obj):
    """Apply all modifiers on an object"""
    import bpy

    for mod in obj.modifiers:
        try:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError:
            logger.warning(f"Cannot apply modifier {mod.name} on {obj.name}")


def deep_copy_material(original_material):
    """Deep copy a material including its node groups"""
    import bpy

    new_mat = original_material.copy()
    new_mat.name = original_material.name + "_deepcopy"

    def duplicate_node_groups(node_tree, group_map=None):
        if group_map is None:
            group_map = {}
        for node in node_tree.nodes:
            if node.type == "GROUP":
                group = node.node_tree
                if group not in group_map:
                    group_copy = group.copy()
                    group_copy.name = f"{group.name}_copy"
                    duplicate_node_groups(group_copy, group_map)
                else:
                    group_copy = group_map[group]
                node.node_tree = group_copy
        return group_map

    if new_mat.use_nodes and new_mat.node_tree:
        duplicate_node_groups(new_mat.node_tree)
    return new_mat


def process_glass_materials(obj):
    """Convert glass BSDF to principled BSDF with transmission for USD compatibility"""
    import bpy

    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        nodes = mat.node_tree.nodes
        if not nodes.get("Material Output"):
            continue
        output = nodes["Material Output"]

        is_glass = False
        if nodes.get("Glass BSDF"):
            if output.inputs[0].links and output.inputs[0].links[0].from_node.bl_idname == "ShaderNodeBsdfGlass":
                is_glass = True
            color = nodes["Glass BSDF"].inputs[0].default_value
            roughness = nodes["Glass BSDF"].inputs[1].default_value
            ior = nodes["Glass BSDF"].inputs[2].default_value

        if "glass" in mat.name.lower() or "shader_lamp_bulb" in mat.name:
            is_glass = True

        if is_glass:
            logger.info(f"Creating glass material on {obj.name}")
            if nodes.get("Principled BSDF"):
                nodes.remove(nodes["Principled BSDF"])
            principled_bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
            if nodes.get("Glass BSDF"):
                principled_bsdf_node.inputs["Base Color"].default_value = color
                principled_bsdf_node.inputs["Roughness"].default_value = roughness
                principled_bsdf_node.inputs["IOR"].default_value = ior
            else:
                principled_bsdf_node.inputs["Roughness"].default_value = 0
            principled_bsdf_node.inputs["Transmission Weight"].default_value = 1
            principled_bsdf_node.inputs["Alpha"].default_value = 0
            mat.node_tree.links.new(
                principled_bsdf_node.outputs[0], nodes["Material Output"].inputs[0]
            )


def remove_params(mat, node_tree):
    """Remove interfering params (metallic, sheen, clearcoat) before baking"""
    nodes = node_tree.nodes
    paramDict = {}
    if nodes.get("Material Output"):
        output = nodes["Material Output"]
    elif nodes.get("Group Output"):
        output = nodes["Group Output"]
    else:
        return paramDict

    if (
        nodes.get("Principled BSDF")
        and output.inputs[0].links
        and output.inputs[0].links[0].from_node.bl_idname == "ShaderNodeBsdfPrincipled"
    ):
        principled_bsdf_node = nodes["Principled BSDF"]
        metal = principled_bsdf_node.inputs["Metallic"].default_value
        sheen = principled_bsdf_node.inputs["Sheen Weight"].default_value
        clearcoat = principled_bsdf_node.inputs["Coat Weight"].default_value
        paramDict[mat.name] = {
            "Metallic": metal,
            "Sheen Weight": sheen,
            "Coat Weight": clearcoat,
        }
        principled_bsdf_node.inputs["Metallic"].default_value = 0
        principled_bsdf_node.inputs["Sheen Weight"].default_value = 0
        principled_bsdf_node.inputs["Coat Weight"].default_value = 0
        return paramDict

    for node in nodes:
        if node.type == "GROUP":
            paramDict = remove_params(mat, node.node_tree)
            if paramDict:
                return paramDict

    return paramDict


def process_interfering_params(obj):
    """Process interfering params for all materials on an object"""
    paramDict = {}
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        paramDict.update(remove_params(mat, mat.node_tree))
    return paramDict


def bake_pass(obj, dest: Path, img_size, bake_type):
    """Bake a single pass (DIFFUSE, ROUGHNESS, NORMAL, etc.) for an object"""
    import bpy

    img = bpy.data.images.new(f"{obj.name}_{bake_type}", img_size, img_size)
    clean_name = obj.name.replace(" ", "_").replace(".", "_").replace("/", "_")
    file_path = dest / f"{clean_name}_{bake_type}.png"

    bake_obj = False
    bake_exclude_mats = {}

    for index, slot in reversed(list(enumerate(obj.material_slots))):
        mat = slot.material
        if mat is None:
            bpy.context.object.active_material_index = index
            bpy.ops.object.material_slot_remove()
            continue

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        output = nodes["Material Output"]

        img_node = nodes.new("ShaderNodeTexImage")
        img_node.name = f"{bake_type}_node"
        img_node.image = img
        img_node.select = True
        nodes.active = img_node

        if len(output.inputs[0].links) == 0:
            logger.info(f"{mat.name} has no surface output, not using baked textures")
            bake_exclude_mats[mat] = img_node
            continue

        bake_obj = True

    if bake_type in SPECIAL_BAKE:
        internal_bake_type = "EMIT"
    else:
        internal_bake_type = bake_type

    if bake_obj:
        logger.info(f"Baking {bake_type} pass for {obj.name}")
        bpy.ops.object.bake(
            type=internal_bake_type, pass_filter={"COLOR"}, save_mode="EXTERNAL"
        )
        img.filepath_raw = str(file_path)
        img.save()
        logger.info(f"Saved to {file_path}")

    for mat, img_node in bake_exclude_mats.items():
        mat.node_tree.nodes.remove(img_node)


def bake_special_emit(obj, dest, img_size, bake_type):
    """Bake special passes (METAL, TRANSMISSION) that need emit workaround"""
    import bpy

    should_bake = False
    links_removed = []
    links_added = []

    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue

        nodes = mat.node_tree.nodes
        principled_bsdf_node = None
        root_node = None

        for node in nodes:
            if node.type != "GROUP":
                continue
            for subnode in node.node_tree.nodes:
                if subnode.type == "BSDF_PRINCIPLED":
                    principled_bsdf_node = subnode
                    root_node = node

        if nodes.get("Principled BSDF"):
            principled_bsdf_node = nodes["Principled BSDF"]
            root_node = mat
        elif not principled_bsdf_node:
            continue
        elif ALL_BAKE[bake_type] not in principled_bsdf_node.inputs:
            continue

        outputSoc = principled_bsdf_node.outputs[0].links[0].to_socket
        l = principled_bsdf_node.outputs[0].links[0]
        from_socket, to_socket = l.from_socket, l.to_socket
        root_node.node_tree.links.remove(l)
        links_removed.append((root_node, from_socket, to_socket))

        bake_input = principled_bsdf_node.inputs[ALL_BAKE[bake_type]]
        bake_val = bake_input.default_value

        if bake_val > 0:
            should_bake = True

        col = root_node.node_tree.nodes.new("ShaderNodeRGB")
        col.outputs[0].default_value = (bake_val, bake_val, bake_val, 1.0)
        new_link = root_node.node_tree.links.new(col.outputs[0], outputSoc)
        links_added.append((root_node, col.outputs[0], outputSoc))

    if should_bake:
        bake_pass(obj, dest, img_size, bake_type)

    # Undo temporary changes
    for n, from_soc, to_soc in links_added:
        for l in n.node_tree.links:
            if l.from_socket == from_soc and l.to_socket == to_soc:
                n.node_tree.links.remove(l)

    for n, from_soc, to_soc in links_removed:
        n.node_tree.links.new(from_soc, to_soc)


def apply_baked_tex(obj, paramDict=None):
    """Replace procedural nodes with baked texture nodes"""
    import bpy

    if paramDict is None:
        paramDict = {}

    bpy.context.view_layer.objects.active = obj
    if "ExportUV" in obj.data.uv_layers:
        obj.data.uv_layers["ExportUV"].active_render = True
    for uv_layer in reversed(obj.data.uv_layers):
        if "ExportUV" not in uv_layer.name:
            obj.data.uv_layers.remove(uv_layer)

    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        logger.info("Reapplying baked textures on " + mat.name)

        # Delete all nodes except baked nodes and bsdf
        excludedNodes = [type + "_node" for type in ALL_BAKE]
        excludedNodes.extend(["Material Output", "Principled BSDF"])
        for n in list(nodes):
            if n.name not in excludedNodes:
                nodes.remove(n)

        output = nodes["Material Output"]

        # Setup principled BSDF
        if nodes.get("Principled BSDF") is None:
            principled_bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
        elif (
            len(output.inputs[0].links) != 0
            and output.inputs[0].links[0].from_node.bl_idname == "ShaderNodeBsdfPrincipled"
        ):
            principled_bsdf_node = nodes["Principled BSDF"]
        else:
            nodes.remove(nodes["Principled BSDF"])
            principled_bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")

        links = mat.node_tree.links
        links.new(output.inputs[0], principled_bsdf_node.outputs[0])

        for bake_type in ALL_BAKE:
            if not nodes.get(bake_type + "_node"):
                continue
            tex_node = nodes[bake_type + "_node"]
            if bake_type == "NORMAL":
                normal_node = nodes.new("ShaderNodeNormalMap")
                links.new(normal_node.inputs["Color"], tex_node.outputs[0])
                links.new(
                    principled_bsdf_node.inputs[ALL_BAKE[bake_type]], normal_node.outputs[0]
                )
                continue
            links.new(principled_bsdf_node.inputs[ALL_BAKE[bake_type]], tex_node.outputs[0])

        # Restore cleared param values
        if mat.name in paramDict:
            principled_bsdf_node.inputs["Metallic"].default_value = paramDict[mat.name]["Metallic"]
            principled_bsdf_node.inputs["Sheen Weight"].default_value = paramDict[mat.name]["Sheen Weight"]
            principled_bsdf_node.inputs["Coat Weight"].default_value = paramDict[mat.name]["Coat Weight"]


def bake_object(obj, dest: Path, img_size):
    """Full bake pipeline for a single object"""
    if not uv_unwrap(obj):
        return

    import bpy
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Deep copy materials (in case of shared materials across meshes)
    for slot in obj.material_slots:
        mat = slot.material
        if mat is not None:
            slot.material = deep_copy_material(mat)

    process_glass_materials(obj)

    # Bake special passes first (METAL, TRANSMISSION)
    for bake_type in SPECIAL_BAKE:
        bake_special_emit(obj, dest, img_size, bake_type)

    # Remove interfering params before standard baking
    paramDict = process_interfering_params(obj)

    # Bake standard passes (DIFFUSE, ROUGHNESS, NORMAL)
    for bake_type in BAKE_TYPES:
        bake_pass(obj, dest, img_size, bake_type)

    # Apply baked textures
    apply_baked_tex(obj, paramDict)


def bake_scene(output_dir: str, image_res: int = 1024):
    """Bake all mesh objects in the current scene"""
    import bpy

    textures_dir = Path(output_dir) / "textures"
    textures_dir.mkdir(parents=True, exist_ok=True)

    mesh_objects = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and obj in list(bpy.context.view_layer.objects)
    ]
    total = len(mesh_objects)
    logger.info(f"Starting texture baking for {total} mesh objects (resolution: {image_res}px)")

    # Setup Cycles for baking
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "GPU"
    bpy.context.scene.cycles.samples = 1
    bpy.context.scene.cycles.tile_x = image_res
    bpy.context.scene.cycles.tile_y = image_res

    for i, obj in enumerate(mesh_objects, 1):
        logger.info(f"[{i}/{total}] Baking: {obj.name}")

        if not obj.data.materials:
            logger.info("  No material, skipping...")
            continue
        if len(obj.data.vertices) == 0:
            logger.info("  No vertices, skipping...")
            continue

        # Apply modifiers first
        obj.hide_render = False
        obj.hide_viewport = False
        apply_all_modifiers(obj)

        bake_object(obj, textures_dir, image_res)

        obj.hide_render = True
        obj.hide_viewport = True

    # Restore visibility for export
    for obj in bpy.data.objects:
        obj.hide_viewport = obj.hide_render

    logger.info(f"Texture baking complete. Textures saved to: {textures_dir}")
    return textures_dir


# ─── Main Conversion Function ───


def convert_blend_to_usd(
    blend_path: str,
    usd_path: str,
    selected_objects_only: bool = False,
    visible_objects_only: bool = True,
    export_animation: bool = False,
    export_materials: bool = True,
    export_textures: bool = False,
    export_uvmaps: bool = True,
    export_normals: bool = True,
    export_mesh_colors: bool = True,
    export_hair: bool = False,
    export_armatures: bool = True,
    export_shapekeys: bool = True,
    use_instancing: bool = True,
    generate_preview_surface: bool = True,
    convert_orientation: bool = False,
    root_prim_path: str = "",
    overwrite: bool = False,
    bake_textures: bool = False,
    bake_resolution: int = 1024,
):
    """将 .blend 文件转换为 USD 格式"""

    if not os.path.isfile(blend_path):
        print(f"[ERROR] Blend file not found: {blend_path}")
        return False

    if os.path.exists(usd_path) and not overwrite:
        print(f"[SKIP] Output already exists: {usd_path} (use --overwrite to force)")
        return True

    usd_dir = os.path.dirname(usd_path) or "."
    os.makedirs(usd_dir, exist_ok=True)

    import bpy

    print(f"[INFO] Opening: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    # 统计场景信息
    scene = bpy.context.scene
    num_objects = len(scene.objects)
    num_meshes = sum(1 for o in scene.objects if o.type == "MESH")
    num_lights = sum(1 for o in scene.objects if o.type == "LIGHT")
    num_cameras = sum(1 for o in scene.objects if o.type == "CAMERA")
    print(f"[INFO] Scene: {num_objects} objects ({num_meshes} meshes, {num_lights} lights, {num_cameras} cameras)")

    # 纹理烘焙：将程序化材质节点烘焙为纹理贴图
    if bake_textures:
        print(f"\n[INFO] Baking procedural materials to textures (resolution: {bake_resolution}px)...")
        print("[INFO] This may take a while depending on the number of objects...")
        bake_scene(usd_dir, image_res=bake_resolution)
        # After baking, we must export textures
        export_textures = True
        print("[INFO] Texture baking complete!\n")

    # 构建 USD 导出参数
    export_kwargs = {
        "filepath": usd_path,
        "selected_objects_only": selected_objects_only,
        "visible_objects_only": visible_objects_only,
        "export_animation": export_animation,
        "export_hair": export_hair,
        "export_uvmaps": export_uvmaps,
        "export_normals": export_normals,
        "export_mesh_colors": export_mesh_colors,
        "export_materials": export_materials,
        "export_armatures": export_armatures,
        "export_shapekeys": export_shapekeys,
        "use_instancing": use_instancing,
        "generate_preview_surface": generate_preview_surface,
        "export_textures": export_textures,
        "overwrite_textures": overwrite,
        "convert_orientation": convert_orientation,
    }

    if root_prim_path:
        export_kwargs["root_prim_path"] = root_prim_path

    print(f"[INFO] Exporting to: {usd_path}")
    bpy.ops.wm.usd_export(**export_kwargs)

    # 验证输出
    if os.path.isfile(usd_path):
        size_mb = os.path.getsize(usd_path) / (1024 * 1024)
        print(f"[OK] Export successful: {usd_path} ({size_mb:.1f} MB)")
        if export_textures:
            tex_dir = os.path.join(usd_dir, "textures")
            if os.path.isdir(tex_dir):
                tex_count = len([f for f in os.listdir(tex_dir) if f.endswith(".png")])
                print(f"[OK] Textures: {tex_count} PNG files in {tex_dir}")
        return True
    else:
        print(f"[ERROR] Export failed: output file not created")
        return False


def batch_convert(
    input_dir: str,
    output_dir: str,
    pattern: str = "*.blend",
    **kwargs,
):
    """批量转换目录下所有 .blend 文件"""

    blend_files = sorted(glob.glob(os.path.join(input_dir, pattern), recursive=True))
    if not blend_files:
        print(f"[WARN] No .blend files found in: {input_dir}")
        return

    print(f"[INFO] Found {len(blend_files)} .blend file(s) in {input_dir}")

    success_count = 0
    fail_count = 0

    for i, blend_path in enumerate(blend_files, 1):
        rel_path = os.path.relpath(blend_path, input_dir)
        usd_rel_path = os.path.splitext(rel_path)[0] + ".usdc"
        usd_path = os.path.join(output_dir, usd_rel_path)

        print(f"\n--- [{i}/{len(blend_files)}] {rel_path} ---")
        ok = convert_blend_to_usd(blend_path, usd_path, **kwargs)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    print(f"\n[DONE] Batch conversion: {success_count} success, {fail_count} failed, {len(blend_files)} total")


def main():
    parser = argparse.ArgumentParser(
        description="Convert Blender .blend files to USD format (with texture baking support)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # With texture baking (RECOMMENDED - fixes gray materials)
  python blend2usd.py scene.blend -o scene.usdc --bake-textures

  # Without baking (faster but materials may appear gray)
  python blend2usd.py scene.blend -o scene.usdc

  # High resolution baking
  python blend2usd.py scene.blend -o scene.usdc --bake-textures --bake-resolution 2048

  # ASCII USD format
  python blend2usd.py scene.blend -o scene.usda --bake-textures

  # Batch convert with baking
  python blend2usd.py ./blends/ -o ./usd/ --batch --bake-textures
        """,
    )

    parser.add_argument("input", help="Input .blend file or directory (for batch mode)")
    parser.add_argument("-o", "--output", required=True, help="Output .usd/.usdc/.usda file or directory (for batch mode)")
    parser.add_argument("--batch", action="store_true", help="Batch convert all .blend files in input directory")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    parser.add_argument("--bake-textures", action="store_true", help="Bake procedural materials to textures before export (fixes gray materials)")
    parser.add_argument("--bake-resolution", type=int, default=1024, help="Texture baking resolution in pixels (default: 1024)")
    parser.add_argument("--selected-only", action="store_true", help="Export selected objects only")
    parser.add_argument("--visible-only", action="store_true", default=True, help="Export visible objects only (default: True)")
    parser.add_argument("--export-animation", action="store_true", help="Export animation data")
    parser.add_argument("--no-materials", action="store_true", help="Do not export materials")
    parser.add_argument("--export-textures", action="store_true", help="Export textures alongside USD")
    parser.add_argument("--no-uvmaps", action="store_true", help="Do not export UV maps")
    parser.add_argument("--no-normals", action="store_true", help="Do not export custom normals")
    parser.add_argument("--export-hair", action="store_true", help="Export hair particle systems")
    parser.add_argument("--no-armatures", action="store_true", help="Do not export armatures")
    parser.add_argument("--no-shapekeys", action="store_true", help="Do not export shape keys")
    parser.add_argument("--no-instancing", action="store_true", help="Do not use instancing for duplicated objects")
    parser.add_argument("--root-prim", default="", help="Root prim path in USD (e.g. '/World')")

    args = parser.parse_args()

    # 设置环境变量（确保 conda 环境库优先）
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        lib_path = os.path.join(conda_prefix, "lib")
        current_ld = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_path not in current_ld:
            os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{current_ld}"
        qt_plugin = os.path.join(conda_prefix, "lib", "qt6", "plugins")
        os.environ["QT_PLUGIN_PATH"] = qt_plugin

    kwargs = {
        "selected_objects_only": args.selected_only,
        "visible_objects_only": args.visible_only,
        "export_animation": args.export_animation,
        "export_materials": not args.no_materials,
        "export_textures": args.export_textures,
        "export_uvmaps": not args.no_uvmaps,
        "export_normals": not args.no_normals,
        "export_hair": args.export_hair,
        "export_armatures": not args.no_armatures,
        "export_shapekeys": not args.no_shapekeys,
        "use_instancing": not args.no_instancing,
        "generate_preview_surface": True,
        "convert_orientation": False,
        "root_prim_path": args.root_prim,
        "overwrite": args.overwrite,
        "bake_textures": args.bake_textures,
        "bake_resolution": args.bake_resolution,
    }

    if args.batch:
        batch_convert(args.input, args.output, **kwargs)
    else:
        # 自动推断输出格式
        output_path = args.output
        ext = os.path.splitext(output_path)[1].lower()
        if ext not in (".usd", ".usdc", ".usda"):
            output_path = output_path + ".usdc"
            print(f"[INFO] No USD extension specified, defaulting to: {output_path}")

        success = convert_blend_to_usd(args.input, output_path, **kwargs)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
