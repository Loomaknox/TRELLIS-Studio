"""Factory-scene CPU PBR transfer for baked_game_copy.py; no user scene access."""
from pathlib import Path
import json
import math
import sys
import time

import bpy
import numpy as np


def _repair_baked_normals(image):
    pixels = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgb = pixels.reshape(-1, 4)[:, :3]
    # A transfer ray can hit the opposite wall of a thin shell. A baked
    # tangent-space vector pointing below the target surface inverts its shading.
    # Use the target shading normal there and where there is no usable vector.
    invalid = (
        (rgb[:, 2] < .5)
        | ~np.isfinite(rgb).all(axis=1)
        | (np.abs(rgb - .5).max(axis=1) <= 1.0 / 255.0)
    )
    changed = int(np.count_nonzero(invalid))
    if changed:
        rgb[invalid] = (.5, .5, 1.)
        image.pixels.foreach_set(pixels)
        image.update()
    return changed


def main():
    stage = Path(sys.argv[sys.argv.index('--') + 1])
    request = json.loads((stage / 'request.json').read_text(encoding='utf-8'))
    options = request['options']
    size = options['texture_size']
    started = time.monotonic()

    def progress(label, fraction):
        temporary = stage / 'progress.pending.json'
        temporary.write_text(json.dumps(dict(stage=label, fraction=fraction)), encoding='utf-8')
        temporary.replace(stage / 'progress.json')

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 3
    bpy.ops.import_scene.gltf(filepath=str(stage / 'donor.glb'))
    donor = next(obj for obj in scene.objects if obj.type == 'MESH')
    donor.name = 'HD donor'
    material = donor.data.materials[0]
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = next(node for node in nodes if node.type == 'BSDF_PRINCIPLED')
    output = next(node for node in nodes if node.type == 'OUTPUT_MATERIAL')
    surface = output.inputs['Surface'].links[0].from_socket
    emission = nodes.new('ShaderNodeEmission')
    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    combine.inputs['Red'].default_value = 1

    def connect(source, target):
        if source.is_linked:
            links.new(source.links[0].from_socket, target)
        else:
            target.default_value = source.default_value

    connect(bsdf.inputs['Roughness'], combine.inputs['Green'])
    connect(bsdf.inputs['Metallic'], combine.inputs['Blue'])
    target = np.load(stage / 'target.npz')
    # GLB is Y-up; Blender's glTF importer maps it to Z-up.
    vertices = target['vertices'][:, [0, 2, 1]] * [1, -1, 1]
    mesh = bpy.data.meshes.new('Game geometry')
    mesh.from_pydata(vertices, [], target['faces'])
    mesh.validate(clean_customdata=False)
    mesh.update()
    low = bpy.data.objects.new('Game copy', mesh)
    scene.collection.objects.link(low)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    mesh.uv_layers.new(name='UVMap')
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.008, area_weight=.5,
                             correct_aspect=True, scale_to_bounds=False, margin_method='ADD')
    bpy.ops.object.mode_set(mode='OBJECT')
    # Geometry is already triangles; bake and export use exactly the same corners.
    target_material = bpy.data.materials.new('Baked PBR')
    target_material.use_nodes = True
    target_material.use_backface_culling = not request['double_sided']
    mesh.materials.append(target_material)
    target_nodes, target_links = target_material.node_tree.nodes, target_material.node_tree.links
    target_bsdf = next(node for node in target_nodes if node.type == 'BSDF_PRINCIPLED')
    extent = float(np.ptp(vertices, axis=0).max())
    # Scale the pilot cages to the donor, rather than assuming every asset is 1.75 m.
    if options['profile'] == 'humanoid':
        height = float(np.ptp(vertices[:, 2]))
        cage, ray = height * .00457, height * .02
    else:
        cage, ray = extent * .0052, extent * .026
    channels = ['base_color', 'metallic_roughness'] + (['normal'] if options['bake_normals'] else []) + ['hit_mask']
    labels = dict(base_color='Baking base colour', metallic_roughness='Baking roughness and metallic',
                  normal='Baking tangent-space detail', hit_mask='Measuring unpadded transfer coverage')
    repaired_normal_texels = 0
    for index, channel in enumerate(channels):
        progress(labels[channel], .45 + index * .1)
        image = bpy.data.images.new(channel, width=size, height=size, alpha=True, float_buffer=False)
        image.colorspace_settings.name = 'sRGB' if channel == 'base_color' else 'Non-Color'
        image.generated_color = (.5, .5, 1, 1) if channel == 'normal' else (0, 0, 0, 0)
        node = target_nodes.new('ShaderNodeTexImage')
        node.image, node.name = image, channel
        target_nodes.active = node
        if channel == 'normal':
            links.new(surface, output.inputs['Surface'])
            bake_type = 'NORMAL'
        else:
            for link in list(emission.inputs['Color'].links):
                links.remove(link)
            if channel == 'base_color':
                connect(bsdf.inputs['Base Color'], emission.inputs['Color'])
            elif channel == 'metallic_roughness':
                links.new(combine.outputs['Color'], emission.inputs['Color'])
            else:
                emission.inputs['Color'].default_value = (1, 1, 1, 1)
            links.new(emission.outputs['Emission'], output.inputs['Surface'])
            bake_type = 'EMIT'
        bpy.ops.object.select_all(action='DESELECT')
        donor.select_set(True)
        low.select_set(True)
        bpy.context.view_layer.objects.active = low
        bpy.ops.object.bake(type=bake_type, use_selected_to_active=True, normal_space='TANGENT',
                            normal_r='POS_X', normal_g='POS_Y', normal_b='POS_Z', use_clear=False,
                            cage_extrusion=cage, max_ray_distance=ray,
                            margin=0 if channel == 'hit_mask' else 8, margin_type='EXTEND')
        if channel == 'normal':
            repaired_normal_texels = _repair_baked_normals(image)
        image.file_format = 'PNG'
        image.filepath_raw = str(stage / (channel + '.png'))
        image.save()
    links.new(surface, output.inputs['Surface'])
    target_links.new(target_nodes['base_color'].outputs['Color'], target_bsdf.inputs['Base Color'])
    separate = target_nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    target_links.new(target_nodes['metallic_roughness'].outputs['Color'], separate.inputs['Color'])
    target_links.new(separate.outputs['Green'], target_bsdf.inputs['Roughness'])
    target_links.new(separate.outputs['Blue'], target_bsdf.inputs['Metallic'])
    if options['bake_normals']:
        normal = target_nodes.new('ShaderNodeNormalMap')
        normal.space = 'TANGENT'
        target_links.new(target_nodes['normal'].outputs['Color'], normal.inputs['Color'])
        target_links.new(normal.outputs['Normal'], target_bsdf.inputs['Normal'])
    progress('Exporting the baked game copy', .9)
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.export_scene.gltf(filepath=str(stage / 'model.glb'), export_format='GLB', use_selection=True,
                              export_apply=True, export_tangents=True, export_normals=True, export_yup=True,
                              export_materials='EXPORT', export_image_format='AUTO', export_animations=False)
    report = dict(engine='Blender Cycles CPU', blender=bpy.app.version_string, threads=3,
                  texture_size=size, channels=[c for c in channels if c != 'hit_mask'],
                  uv='Smart Project: 66 degrees, island margin 0.008, area weight 0.5',
                  cage_extrusion=cage, max_ray_distance=ray, gutter_px=8,
                  normal_format='Tangent-space +Y, fixed triangle corners and exported tangents',
                  repaired_normal_texels=repaired_normal_texels,
                  seconds=round(time.monotonic() - started, 3))
    (stage / 'bake-report.json').write_text(json.dumps(report), encoding='utf-8')


if __name__ == '__main__':
    main()
