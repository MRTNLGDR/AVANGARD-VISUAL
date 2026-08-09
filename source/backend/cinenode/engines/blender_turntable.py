"""Headless Blender helper used by the mesh.preview node.

Executed inside Blender, not imported by the server runtime.
"""
from __future__ import annotations

import math
import pathlib
import sys

import bpy
from mathutils import Vector


def args_after_separator() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def import_mesh(path: str) -> None:
    suffix = pathlib.Path(path).suffix.lower()
    if suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=path)
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif suffix == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif suffix == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    else:
        raise RuntimeError(f"Unsupported mesh: {suffix}")


def world_bounds() -> tuple[Vector, Vector]:
    points = []
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        raise RuntimeError("No mesh objects imported")
    return (
        Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
        Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))),
    )


def main() -> None:
    source, destination, width, height, frames, fps = args_after_separator()
    width, height, frames, fps = map(int, (width, height, frames, fps))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_mesh(source)
    low, high = world_bounds()
    center = (low + high) / 2
    extent = max((high - low).length, 0.1)

    root = bpy.data.objects.new("Turntable", None)
    bpy.context.collection.objects.link(root)
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH":
            obj.parent = root
            obj.location -= center

    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    camera.location = (extent * 1.55, -extent * 1.55, extent * 0.75)

    direction = Vector((0, 0, 0)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = 52

    key_data = bpy.data.lights.new("Key", type="AREA")
    key_data.energy = 1200
    key_data.shape = "DISK"
    key_data.size = extent
    key = bpy.data.objects.new("Key", key_data)
    bpy.context.collection.objects.link(key)
    key.location = (extent, -extent, extent * 1.5)

    fill_data = bpy.data.lights.new("Fill", type="AREA")
    fill_data.energy = 700
    fill_data.size = extent
    fill = bpy.data.objects.new("Fill", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = (-extent, -extent * 0.5, extent)

    root.rotation_euler.z = 0
    root.keyframe_insert(data_path="rotation_euler", frame=1, index=2)
    root.rotation_euler.z = math.tau
    root.keyframe_insert(data_path="rotation_euler", frame=frames + 1, index=2)
    if root.animation_data and root.animation_data.action:
        for curve in root.animation_data.action.fcurves:
            for keyframe in curve.keyframe_points:
                keyframe.interpolation = "LINEAR"

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frames
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.filepath = destination
    scene.world.color = (0.025, 0.025, 0.035)
    bpy.ops.render.render(animation=True)


main()
