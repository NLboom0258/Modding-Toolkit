import bpy

from ...core.i18n import T
from ...core.mdf_tex_processor_ui_base import MdfTexDialogBase
from .mdf_tex_processor import DMC5_COMMON_SLOT_TYPES, DMC5_NULL_TEX_BY_TYPE


class DMC5_OT_MdfTexProcessorDialog(MdfTexDialogBase):
    """MDF2 Processor - process textures on top of an existing MDF2 material"""
    bl_idname = "dmc5.mdf_tex_processor_dialog"
    bl_label  = "MDF2 + Tex Processor"

    @classmethod
    def description(cls, context, properties):
        return T("dmc5.mdf_tex_processor_ui.dialog_desc")

    _game_prefix       = "dmc5"
    _settings_attr     = "dmc5_mdf_tex_processor"
    _natives_root_key  = "dmc5_natives_root"
    _root_label        = "Natives Root"
    _path_prefix_label = "natives/x64/"
    _path_hint         = "e.g. Character/pl0100/"
    _common_slot_types = DMC5_COMMON_SLOT_TYPES
    _null_tex_by_type  = DMC5_NULL_TEX_BY_TYPE


classes = [DMC5_OT_MdfTexProcessorDialog]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
