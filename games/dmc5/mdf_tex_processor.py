import bpy
import os

from ...core.mdf_tex_processor_base import (
    BASE_SLOT_CHANNEL_MAPS, BASE_NULL_TEX_BY_TYPE, BASE_TEXTURE_TYPE_ABBREV,
    BASE_COMMON_SLOT_TYPES,
    PBR_TYPES, PBR_TYPE_LABELS, PBR_CHANNEL_SELECTABLE, SRGB_SLOT_TYPES,
    _CH_ENUM_ITEMS,
    make_null_checker, make_collection_update_cb, mdf_collection_poll,
    MdfTexMaterialItem,
    MdfTexRefreshBase, MdfTexPickPBRBase, MdfTexPickDirectBase,
    MdfTexClearPBRBase, MdfTexClearDirectBase,
    MdfTexCopyMaterialBase, MdfTexPasteMaterialBase,
    MdfTexProcessBase,
)

# ── DMC5 Constants (built from a real 3Dmigoto dump + real mdf2 materials) ──────

# DMC5 纹理版本号 (.tex.NNN) -- 用户提供: 11
DMC5_TEX_VERSION = 11

DMC5_TEXTURE_TYPE_ABBREV = {
    **BASE_TEXTURE_TYPE_ABBREV,
    'BaseMetalMap': 'ALBM',
    'AlphaTranslucentOcclusionEmissiveMap': 'ATOS',
    'TimeLock_EmissiveColor': 'TIMELOCK',
}

# DMC5 channel maps: base colour RGB + metallic A (direct, NOT inverted);
# ATOS-E packs alpha R / translucency G / AO B / emissive A; TimeLock is a
# time-stop emissive colour map (RGB = emissive, A unused).
DMC5_SLOT_CHANNEL_MAPS = {
    **BASE_SLOT_CHANNEL_MAPS,
    'BaseMetalMap': {
        'R': ('color', 0),
        'G': ('color', 1),
        'B': ('color', 2),
        'A': ('metallic', 0),
    },
    'AlphaTranslucentOcclusionEmissiveMap': {
        'R': ('alpha', 0),
        'G': ('translucency', 0),
        'B': ('ao', 0),
        'A': ('emissive', 0),
    },
    'TimeLock_EmissiveColor': {
        'R': ('emissive', 0),
        'G': ('emissive', 1),
        'B': ('emissive', 2),
        'A': None,
    },
}

DMC5_COMMON_SLOT_TYPES = BASE_COMMON_SLOT_TYPES | {
    'BaseMetalMap',
    'AlphaTranslucentOcclusionEmissiveMap',
    'TimeLock_EmissiveColor',
}

DMC5_NULL_TEX_BY_TYPE = {
    **BASE_NULL_TEX_BY_TYPE,
    'BaseMetalMap': 'systems/rendering/NullBlack.tex',
    'AlphaTranslucentOcclusionEmissiveMap': 'systems/rendering/NullATOS.tex',
    'TimeLock_EmissiveColor': 'systems/rendering/NullBlack.tex',
}

# ── Null checker + collection update callback ──────────────────────────────────

_is_null_dmc5              = make_null_checker(DMC5_NULL_TEX_BY_TYPE)
_on_dmc5_collection_update = make_collection_update_cb(_is_null_dmc5)


# ── Settings PropertyGroup ─────────────────────────────────────────────────────

class DMC5MdfTexProcessorSettings(bpy.types.PropertyGroup):
    mdf_collection: bpy.props.PointerProperty(
        name="MDF Collection",
        type=bpy.types.Collection,
        description="Target MDF2 collection to process",
        poll=mdf_collection_poll,
        update=_on_dmc5_collection_update,
    )
    texture_base_path: bpy.props.StringProperty(
        name="Base Path",
        description="Path under natives/STM/ (e.g. Character/pl0100)",
        default="",
    )
    materials:             bpy.props.CollectionProperty(type=MdfTexMaterialItem)
    materials_index:       bpy.props.IntProperty()
    clipboard_json:        bpy.props.StringProperty(default="")
    mdf_loaded_collection: bpy.props.StringProperty(default="")


# ── Operators ──────────────────────────────────────────────────────────────────

class DMC5_OT_MdfTexRefresh(MdfTexRefreshBase):
    bl_idname      = "dmc5.mdf_tex_refresh"
    _settings_attr = "dmc5_mdf_tex_processor"
    _is_null_fn    = staticmethod(_is_null_dmc5)


class DMC5_OT_MdfTexPickPBR(MdfTexPickPBRBase):
    bl_idname      = "dmc5.mdf_tex_pick_pbr"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexPickDirect(MdfTexPickDirectBase):
    bl_idname      = "dmc5.mdf_tex_pick_direct"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexClearPBR(MdfTexClearPBRBase):
    bl_idname      = "dmc5.mdf_tex_clear_pbr"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexClearDirect(MdfTexClearDirectBase):
    bl_idname      = "dmc5.mdf_tex_clear_direct"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexCopyMaterial(MdfTexCopyMaterialBase):
    bl_idname      = "dmc5.mdf_tex_copy_material"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexPasteMaterial(MdfTexPasteMaterialBase):
    bl_idname      = "dmc5.mdf_tex_paste_material"
    _settings_attr = "dmc5_mdf_tex_processor"


class DMC5_OT_MdfTexProcess(MdfTexProcessBase):
    bl_idname         = "dmc5.mdf_tex_process"
    _settings_attr    = "dmc5_mdf_tex_processor"
    _natives_root_key = "dmc5_natives_root"
    _null_tex_by_type = DMC5_NULL_TEX_BY_TYPE
    _channel_maps     = DMC5_SLOT_CHANNEL_MAPS
    _tex_version      = DMC5_TEX_VERSION
    _abbrev_map       = DMC5_TEXTURE_TYPE_ABBREV
    _use_art_prefix    = False
    _path_fixed_prefix = ""   # DMC5 assets 直接放 natives/x64/<base> 下（re4 才有固定前缀）
    _platform_segment  = "x64"  # DMC5 用 natives/x64/ (不是 STM)
    _log_tag           = "DMC5 MDF Tex"


# ── Registration ───────────────────────────────────────────────────────────────

class DMC5_OT_SetNativesRoot(bpy.types.Operator):
    """选择 DMC5 Mod 根目录（natives/x64 的上级）。若选中的文件夹本身名为 natives，取其上级。"""
    bl_idname = "dmc5.set_natives_root"
    bl_label = "Set Natives Root"
    bl_options = {'REGISTER'}
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self.directory.rstrip("/\\")
        if os.path.basename(path).lower() == "natives":
            path = os.path.dirname(path)
        context.scene["dmc5_natives_root"] = path
        self.report({'INFO'}, f"DMC5 Mod root: {path}")
        return {'FINISHED'}


classes = [
    DMC5MdfTexProcessorSettings,
    DMC5_OT_SetNativesRoot,
    DMC5_OT_MdfTexRefresh,
    DMC5_OT_MdfTexPickPBR,
    DMC5_OT_MdfTexPickDirect,
    DMC5_OT_MdfTexClearPBR,
    DMC5_OT_MdfTexClearDirect,
    DMC5_OT_MdfTexCopyMaterial,
    DMC5_OT_MdfTexPasteMaterial,
    DMC5_OT_MdfTexProcess,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dmc5_mdf_tex_processor = bpy.props.PointerProperty(
        type=DMC5MdfTexProcessorSettings)
    from ...core.mdf_port_tex import register_game_tex_config
    register_game_tex_config(
        "DMC5",
        abbrev_map=DMC5_TEXTURE_TYPE_ABBREV,
        channel_maps=DMC5_SLOT_CHANNEL_MAPS,
        tex_version=DMC5_TEX_VERSION,
        use_art_prefix=False,
        path_fixed_prefix="",   # TODO(待确认)
        null_tex_by_type=DMC5_NULL_TEX_BY_TYPE,
        natives_root_key="dmc5_natives_root",
        vanilla_asset_rel="assets/dmc5/vanilla_tex_paths.txt",   # (t9 建)
    )


def unregister():
    from ...core.mdf_port_tex import unregister_game_tex_config
    unregister_game_tex_config("DMC5")
    del bpy.types.Scene.dmc5_mdf_tex_processor
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
