import bpy
import json
import os
import shutil

from ...core.i18n import T
from ...core.re_mesh_compat import call_re_mesh_op, re_mesh_op_available
from ...core import console_export
from ...core import export_prep
from mathutils import Matrix


def _get_export_schemes_dir():
    addon_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = os.path.join(addon_dir, "assets", "export_schemes", "dmc5")
    os.makedirs(d, exist_ok=True)
    return d


_scheme_cache = []

def get_schemes_callback(self, context):
    global _scheme_cache
    _scheme_cache = []
    d = _get_export_schemes_dir()
    if os.path.exists(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                name = f.replace('.json', '')
                _scheme_cache.append((f, name, ""))
    if not _scheme_cache:
        _scheme_cache.append(('NONE', "No scheme", ""))
    return _scheme_cache


def _load_scheme(filename):
    filepath = os.path.join(_get_export_schemes_dir(), filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def _make_key(character_id, entry_id, suffix):
    key = f"dmc5ex_{character_id}_{entry_id}_{suffix}"
    return key.replace(" ", "_").replace("(", "").replace(")", "")


def _get_binding(scene, character_id, entry_id, suffix):
    return scene.get(_make_key(character_id, entry_id, suffix), "")


def _set_binding(scene, character_id, entry_id, suffix, value):
    scene[_make_key(character_id, entry_id, suffix)] = value


def _make_en_key(character_id, entry_id, suffix):
    key = f"dmc5en_{character_id}_{entry_id}_{suffix}"
    return key.replace(" ", "_").replace("(", "").replace(")", "")


def _get_enabled(scene, character_id, entry_id, suffix):
    return scene.get(_make_en_key(character_id, entry_id, suffix), True)


def _set_enabled(scene, character_id, entry_id, suffix, value):
    scene[_make_en_key(character_id, entry_id, suffix)] = value


MESH_SETTINGS = {
    "exportAllLODs": True,
    "autoSolveRepeatedUVs": True,
    "preserveSharpEdges": True,
    "rotate90": True,
    "useBlenderMaterialName": False,
    "preserveBoneMatrices": False,
    "exportBoundingBoxes": False,
}


def _do_export_mesh(filepath, collection_name):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    call_re_mesh_op('exportfile', filepath=filepath, targetCollection=collection_name, **MESH_SETTINGS)


def _do_export_mdf2(filepath, collection_name):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    bpy.ops.re_mdf.exportfile(filepath=filepath, targetCollection=collection_name)


def _do_export_chain(filepath, collection_name):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    bpy.ops.re_chain.exportfile(filepath=filepath, targetCollection=collection_name)


def _do_export_fbxskel(filepath, armature_name):
    """Export the mod armature's rest pose as an fbxskel.

    RE Mesh Editor's re_fbxskel.exportfile writes the *current pose* (it always
    passes usePose=True), so we zero every pose bone's matrix_basis first to
    capture the bind/rest pose -- the mod model's default shape -- then restore
    the pose afterwards."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    arm = bpy.data.objects.get(armature_name)
    if arm is None or arm.type != 'ARMATURE':
        raise RuntimeError(f"armature '{armature_name}' not found")
    saved = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones}
    try:
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        bpy.ops.re_fbxskel.exportfile(filepath=filepath, targetArmature=armature_name)
    finally:
        for pb in arm.pose.bones:
            if pb.name in saved:
                pb.matrix_basis = saved[pb.name]


def _get_blank_path_for(rel_path):
    """Return the path to a blank file in blank_files/dmc5/, mirrored from its
    original natives/x64-relative path (e.g. 'character/player/pl0100_dante/pl0100_body/pl0100.mesh.1808282334').
    Storing blanks relative to the natives/x64 root means any directory (character, animation, ...)
    can hold a blank without hard-coding a per-game folder."""
    addon_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(addon_dir, "assets", "blank_files", "dmc5", rel_path.replace("/", os.sep))


def _blank_rels(base_path, rel):
    """Build the natives/x64-relative path for a blank file: strip the platform
    segment (e.g. 'x64') out of base_path, then append the entry's own rel path."""
    segs = [s for s in base_path.split("/") if s and s.lower() != "x64"]
    return "/".join(segs + [rel]) if segs else rel


class DMC5_OT_BatchExport(bpy.types.Operator):
    """DMC5 batch exporter"""
    bl_idname = "dmc5.batch_export"
    bl_label = "DMC5 Batch Export"
    bl_options = {'REGISTER'}

    def execute(self, context):
        show_console = console_export.get_preferences(context).show_console_on_batch_export
        with console_export.kept_open_for_export(show_console):
            return self._execute_with_triangulation(context)

    def _execute_with_triangulation(self, context):
        settings = context.scene.mhw_suite_settings
        if not settings.dmc5_triangulate_face:
            return self._run_export(context)
        with export_prep.triangulated_for_export(context.scene.objects, 'dmc5') as touched:
            if touched:
                print("[DMC5] triangulating {n} face mesh(es) for export".format(n=len(touched)))
            return self._run_export(context)

    def _run_export(self, context):
        scene = context.scene
        settings = scene.mhw_suite_settings

        if not re_mesh_op_available('exportfile'):
            self.report({'ERROR'}, "RE Mesh Editor not installed")
            return {'CANCELLED'}

        natives_root = scene.get("dmc5_natives_root", "")
        if not natives_root or not os.path.isdir(natives_root):
            self.report({'ERROR'}, "Set natives root directory first")
            return {'CANCELLED'}

        scheme_file = settings.dmc5_export_scheme
        if not scheme_file or scheme_file == 'NONE':
            self.report({'ERROR'}, "No export scheme selected")
            return {'CANCELLED'}

        scheme = _load_scheme(scheme_file)
        if not scheme:
            self.report({'ERROR'}, f"Failed to load: {scheme_file}")
            return {'CANCELLED'}

        character_id = scheme["character_id"]
        base_path = scheme["base_path"].replace("\\", "/")
        use_blank = settings.dmc5_use_blank_export

        export_count = 0
        fail_count = 0
        skip_count = 0

        export_cache = {}

        def make_full(rel, bp_override=None):
            bp = (bp_override or base_path).replace("/", os.sep)
            return os.path.join(natives_root, "natives", bp, rel.replace("/", os.sep))

        def try_export(func, filepath, target, label):
            nonlocal export_count, fail_count, skip_count
            if not target or target == "NONE":
                skip_count += 1
                return
            if func == _do_export_fbxskel:
                if target not in bpy.data.objects or bpy.data.objects[target].type != 'ARMATURE':
                    print(f"[DMC5] SKIP {label}: armature '{target}' not found")
                    skip_count += 1
                    return
            elif target not in bpy.data.collections:
                print(f"[DMC5] SKIP {label}: collection '{target}' not found")
                skip_count += 1
                return

            cache_key = (func.__name__, target)
            if cache_key in export_cache:
                try:
                    source_filepath = export_cache[cache_key]
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    shutil.copy2(source_filepath, filepath)
                    print(f"[DMC5] {label}: {target} [CACHED] -> {os.path.basename(filepath)}")
                    export_count += 1
                except Exception as err:
                    print(f"[DMC5] FAILED {label} [CACHE COPY]: {err}")
                    fail_count += 1
                return

            try:
                print(f"[DMC5] {label}: {target} -> {os.path.basename(filepath)}")
                func(filepath, target)
                export_cache[cache_key] = filepath
                export_count += 1
            except Exception as err:
                print(f"[DMC5] FAILED {label}: {err}")
                fail_count += 1

        def try_blank_by_path(rel_path, filepath, label):
            nonlocal export_count, skip_count
            blank_src = _get_blank_path_for(rel_path)
            if os.path.isfile(blank_src):
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                shutil.copy2(blank_src, filepath)
                print(f"[DMC5] {label}: BLANK -> {os.path.basename(filepath)}")
                export_count += 1
            else:
                print(f"[DMC5] SKIP blank (no matching blank file): {rel_path}")
                skip_count += 1

        # --- Per entry (normal mode) ---
        for group in scheme["groups"]:
            group_name = group["name"]
            grp_bp = group.get("base_path")
            for entry in group["entries"]:
                entry_id = entry["id"]

                mesh_en = _get_enabled(scene, character_id, entry_id, "mesh")
                mesh_col = _get_binding(scene, character_id, entry_id, "mesh")
                if entry.get("mesh"):
                    if mesh_en and mesh_col:
                        try_export(_do_export_mesh, make_full(entry["mesh"], grp_bp), mesh_col, f"MESH {entry_id}")
                    elif mesh_en and use_blank:
                        try_blank_by_path(_blank_rels(grp_bp or base_path, entry["mesh"]), make_full(entry["mesh"], grp_bp), f"MESH {entry_id}")

                mdf2_en = _get_enabled(scene, character_id, entry_id, "mdf2")
                mdf2_col = _get_binding(scene, character_id, entry_id, "mdf2")
                if entry.get("mdf2"):
                    if mdf2_en and mdf2_col:
                        for m in entry["mdf2"]:
                            try_export(_do_export_mdf2, make_full(m, grp_bp), mdf2_col, f"MDF2 {entry_id}")
                    elif mdf2_en and use_blank:
                        for m in entry["mdf2"]:
                            try_blank_by_path(_blank_rels(grp_bp or base_path, m), make_full(m, grp_bp), f"MDF2 {entry_id}")

                chain_en = _get_enabled(scene, character_id, entry_id, "chain")
                chain_col = _get_binding(scene, character_id, entry_id, "chain")
                if entry.get("chain"):
                    if chain_en and chain_col:
                        try_export(_do_export_chain, make_full(entry["chain"], grp_bp), chain_col, f"CHAIN {entry_id}")
                    elif chain_en and use_blank:
                        try_blank_by_path(_blank_rels(grp_bp or base_path, entry["chain"]), make_full(entry["chain"], grp_bp), f"CHAIN {entry_id}")

                # --- FBXSKEL（每部位独立：从该 entry 手动选的"无物理骨骨架副本"导出 rest 姿势）---
                if entry.get("fbxskel"):
                    fbx_arm = _get_binding(scene, character_id, entry_id, "fbxskel")
                    if fbx_arm:
                        try_export(_do_export_fbxskel, make_full(entry["fbxskel"], grp_bp), fbx_arm,
                                   f"FBXSKEL {os.path.basename(entry['fbxskel'])}")

        if fail_count > 0:
            self.report({'WARNING'}, f"Done: {export_count} exported, {fail_count} failed, {skip_count} skipped")
        else:
            self.report({'INFO'}, f"Done: {export_count} exported, {skip_count} skipped")
        return {'FINISHED'}


classes = [
    DMC5_OT_BatchExport,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
