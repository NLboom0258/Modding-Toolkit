import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty

from .batch_export import (
    _load_scheme, _get_binding, _set_binding,
    _get_enabled, _set_enabled,
)

EXPORTER_WINDOW_WIDTH = 600

# 备注折行用。Blender 的 invoke_props_dialog 宽度只由 width 参数决定（内容超宽只会被
# 裁、不会把弹窗撑开），所以窗口宽度固定，靠折行保证每条备注都显示得下。
# 字宽是 blf 实测值（blf.size(0, 11)）：'n'/'0'=7、'中'=11、空格=3 —— 不能按
# “CJK 记 2 个单位”估，那会高估两三成、每行都提前换行。
_PX_CJK = 11
_PX_HALF = 7
_PX_SPACE = 3
_DETAIL_PX = 340          # ui_scale=1 时详情列可用于文本的像素宽（600*0.65 - 余量）
_LIST_FACTOR = 0.35       # 左侧组列表占比（与 draw 里的 split factor 一致）


def _char_px(ch):
    """单个字符的估算像素宽度（按 Blender 默认 UI 字号的实测字宽）。"""
    if ch == " ":
        return _PX_SPACE
    return _PX_CJK if ord(ch) > 0x2E7F else _PX_HALF


def _text_px(text):
    """文本的估算像素宽度。"""
    return sum(_char_px(ch) for ch in text)


def _wrap_px(text, max_px):
    """按像素宽度折行（中文没有空格可断，直接硬断）。"""
    lines, cur, cur_w = [], "", 0
    for ch in text:
        cw = _char_px(ch)
        if cur and cur_w + cw > max_px:
            lines.append(cur)
            cur, cur_w = "", 0
        cur += ch
        cur_w += cw
    if cur:
        lines.append(cur)
    return lines or [""]


def _ui_scale(context):
    """界面缩放：高 DPI 下字体与像素同步放大，宽度估算要跟着走。"""
    prefs = getattr(context, "preferences", None)
    sys_prefs = getattr(prefs, "system", None) if prefs is not None else None
    return float(getattr(sys_prefs, "ui_scale", 1.0) or 1.0)


def _get_armatures():
    result = []
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE':
            result.append((obj.name, obj.name, "", 'ARMATURE_DATA', len(result)))
    if not result:
        result.append(("NONE", "No armatures", "", "ERROR", 0))
    return result


def _get_filtered_collections(suffix):
    result = []
    type_map = {"mesh": "RE_MESH_COLLECTION", "mdf2": "RE_MDF_COLLECTION", "chain": "RE_CHAIN_COLLECTION"}
    name_sfx_map = {"mesh": ".mesh", "mdf2": ".mdf2", "chain": ".chain"}
    target_type = type_map.get(suffix, "")
    name_sfx = name_sfx_map.get(suffix, "")
    for c in bpy.data.collections:
        col_type = c.get("~TYPE", "")
        if col_type == target_type:
            icon = f"COLLECTION_{c.color_tag}" if c.color_tag != "NONE" else "OUTLINER_COLLECTION"
            result.append((c.name, c.name, "", icon, len(result)))
            continue
        if not col_type and name_sfx and c.name.endswith(name_sfx):
            result.append((c.name, c.name, "", "OUTLINER_COLLECTION", len(result)))
    if not result:
        result.append(("NONE", "No matching collections", "", "ERROR", 0))
    return result


class DMC5_OT_ToggleEntry(bpy.types.Operator):
    bl_idname = "dmc5.toggle_entry"
    bl_label = "Toggle"
    bl_options = {'INTERNAL'}
    character_id: bpy.props.StringProperty()
    entry_id: bpy.props.StringProperty()
    suffix: bpy.props.StringProperty()
    # 该条目/组默认是否启用（武器组默认 False）。必须与绘制时用同一个默认值，
    # 否则首次点击会“读到 True 再设成 False”而看着没反应。
    default_enabled: bpy.props.BoolProperty(default=True)
    def execute(self, context):
        current = _get_enabled(context.scene, self.character_id, self.entry_id, self.suffix,
                               self.default_enabled)
        _set_enabled(context.scene, self.character_id, self.entry_id, self.suffix, not current)
        return {'FINISHED'}


class DMC5_OT_PickArmature(bpy.types.Operator):
    bl_idname = "dmc5.pick_armature"
    bl_label = "Pick Armature"
    bl_options = {'INTERNAL'}
    bl_property = "armature_name"
    character_id: bpy.props.StringProperty()
    entry_id: bpy.props.StringProperty()
    armature_name: bpy.props.EnumProperty(name="Armature",
        items=lambda self, ctx: _get_armatures())
    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}
    def execute(self, context):
        if self.armature_name != "NONE":
            _set_binding(context.scene, self.character_id, self.entry_id, "fbxskel", self.armature_name)
        return {'FINISHED'}


class DMC5_OT_PickBinding(bpy.types.Operator):
    bl_idname = "dmc5.pick_binding"
    bl_label = "Pick Collection"
    bl_options = {'INTERNAL'}
    bl_property = "collection_name"

    scope: bpy.props.StringProperty(default="ENTRY")
    slot: bpy.props.StringProperty()
    character_id: bpy.props.StringProperty()
    entry_id: bpy.props.StringProperty()
    collection_name: bpy.props.EnumProperty(
        name="Collection",
        items=lambda self, ctx: _get_filtered_collections(self.slot)
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.collection_name != "NONE":
            _set_binding(context.scene, self.character_id, self.entry_id, self.slot,
                         self.collection_name)
        return {'FINISHED'}


class DMC5_OT_ClearEntryBinding(bpy.types.Operator):
    bl_idname = "dmc5.clear_entry_binding"
    bl_label = "Clear Entry Binding"
    bl_options = {'INTERNAL'}
    character_id: bpy.props.StringProperty()
    entry_id: bpy.props.StringProperty()
    suffix: bpy.props.StringProperty()
    def execute(self, context):
        # 清掉该条目的 collection 绑定，回到“未选择”；条目仍启用 -> 走空模型替换逻辑
        _set_binding(context.scene, self.character_id, self.entry_id, self.suffix, "")
        return {'FINISHED'}


class DMC5_GroupListItem(bpy.types.PropertyGroup):
    group_name: StringProperty()
    entry_count: IntProperty()


class DMC5_UL_Groups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        layout.label(text=f"{item.group_name} ({item.entry_count})", icon='FILE_FOLDER')


class DMC5_OT_BatchExportDialog(bpy.types.Operator):
    """DMC5 batch export dialog"""
    bl_idname = "dmc5.batch_export_dialog"
    bl_label = "DMC5 Batch Exporter"
    bl_options = {'REGISTER'}

    groups: CollectionProperty(type=DMC5_GroupListItem)
    group_index: IntProperty()

    def invoke(self, context, event):
        self._ui_scale = _ui_scale(context)
        return context.window_manager.invoke_props_dialog(self, width=EXPORTER_WINDOW_WIDTH)

    def _sync_groups(self, scheme, scheme_file):
        if getattr(self, '_groups_scheme_file', None) == scheme_file:
            return
        self._groups_scheme_file = scheme_file
        self.groups.clear()
        for group in scheme["groups"]:
            item = self.groups.add()
            item.group_name = group["name"]
            item.entry_count = len(group["entries"])
        self.group_index = 0

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.mhw_suite_settings

        layout.prop(settings, "dmc5_export_scheme", text="Character")

        # Natives root
        natives_root = scene.get("dmc5_natives_root", "")
        row = layout.row(align=True)
        row.operator("dmc5.set_natives_root", text="Natives Root", icon='FILE_FOLDER')
        if natives_root:
            parts = natives_root.replace("\\", "/").rstrip("/").split("/")
            short = "/".join(parts[-3:]) if len(parts) > 3 else natives_root
            row.label(text=f".../{short}")
        else:
            row.label(text="Not set", icon='ERROR')

        scheme_file = settings.dmc5_export_scheme
        if not scheme_file or scheme_file == 'NONE':
            layout.label(text="Select a character scheme", icon='INFO')
            return
        scheme = _load_scheme(scheme_file)
        if not scheme:
            layout.label(text="Failed to load scheme", icon='ERROR')
            return

        character_id = scheme["character_id"]
        self._sync_groups(scheme, scheme_file)

        layout.separator()
        layout.prop(settings, "dmc5_use_blank_export", text="Use Blank Model for Unselected", icon='FILE_BLANK')

        layout.separator()
        split = layout.split(factor=0.35)
        col1, col2 = split.column(), split.column()
        col1.template_list("DMC5_UL_Groups", "", self, "groups", self, "group_index",
                           rows=max(4, min(len(self.groups), 10)))

        selected_group = None
        if self.groups and 0 <= self.group_index < len(self.groups):
            item = self.groups[self.group_index]
            selected_group = next((g for g in scheme["groups"] if g["name"] == item.group_name), None)

        if selected_group is not None:
            box = col2.box()
            self._draw_group_detail_normal(box, scene, character_id, selected_group)

    def _draw_group_detail_normal(self, layout, scene, character_id, group):
        layout.label(text=group["name"], icon='FILE_FOLDER')
        for entry in group["entries"]:
            entry_id = entry["id"]
            entry_default = entry.get("enabled", group.get("default_enabled", True))
            entry_box = layout.box()
            note = entry.get("note", "")
            if not note:
                entry_box.label(text=entry_id)
            else:
                # label 不折行、弹窗宽度也固定，超宽会被直接裁掉 —— 这里按详情列的
                # 可用像素折行（用实测字宽算）；续行缩进到第一行备注文字的位置，
                # 缩进量随 id 长度变（用空格拼，实测每个空格 3px）。
                scale = getattr(self, "_ui_scale", 1.0) or 1.0
                avail = _DETAIL_PX / scale          # 高 DPI 下把可用宽度折算回基准像素
                prefix = f"{entry_id}  ["
                indent_px = _text_px(prefix)
                body = avail - indent_px - _text_px("]")
                if body < 40:                       # 装不下几个字：让 id 单独成行
                    entry_box.label(text=entry_id)
                    lines = _wrap_px(note, max(40.0, avail - _text_px("]")))
                    indent, first_prefix = "", ""
                else:
                    lines = _wrap_px(note, body)
                    indent = " " * max(1, int(indent_px / _PX_SPACE))
                    first_prefix = prefix
                for _i, _ln in enumerate(lines):
                    entry_box.label(text=(first_prefix if _i == 0 else indent) + _ln
                                    + ("]" if _i == len(lines) - 1 else ""))

            if entry.get("mesh"):
                head = entry_box.row(align=True)
                en = _get_enabled(scene, character_id, entry_id, "mesh", entry_default)
                op = head.operator("dmc5.toggle_entry", text="",
                                   icon='CHECKBOX_HLT' if en else 'CHECKBOX_DEHLT', emboss=False)
                op.character_id = character_id; op.entry_id = entry_id; op.suffix = "mesh"
                op.default_enabled = entry_default
                cur = _get_binding(scene, character_id, entry_id, "mesh")
                ic = 'OUTLINER_OB_MESH'
                if cur and cur in bpy.data.collections:
                    ct = bpy.data.collections[cur].color_tag
                    if ct != "NONE":
                        ic = f"COLLECTION_{ct}"
                head.label(text="MESH", icon=ic)
                row = entry_box.row(align=True)
                op_p = row.operator("dmc5.pick_binding",
                                    text=cur if cur else "Select...", icon='DOWNARROW_HLT')
                op_p.scope = "ENTRY"; op_p.slot = "mesh"
                op_p.character_id = character_id; op_p.entry_id = entry_id
                if cur:
                    op_c = row.operator("dmc5.clear_entry_binding", text="", icon='X')
                    op_c.character_id = character_id; op_c.entry_id = entry_id; op_c.suffix = "mesh"

            if entry.get("mdf2"):
                head = entry_box.row(align=True)
                en = _get_enabled(scene, character_id, entry_id, "mdf2", entry_default)
                op = head.operator("dmc5.toggle_entry", text="",
                                   icon='CHECKBOX_HLT' if en else 'CHECKBOX_DEHLT', emboss=False)
                op.character_id = character_id; op.entry_id = entry_id; op.suffix = "mdf2"
                op.default_enabled = entry_default
                cur = _get_binding(scene, character_id, entry_id, "mdf2")
                ic = 'MATERIAL'
                if cur and cur in bpy.data.collections:
                    ct = bpy.data.collections[cur].color_tag
                    if ct != "NONE":
                        ic = f"COLLECTION_{ct}"
                head.label(text=f"MDF2 x{len(entry['mdf2'])}", icon=ic)
                row = entry_box.row(align=True)
                op_p = row.operator("dmc5.pick_binding",
                                    text=cur if cur else "Select...", icon='DOWNARROW_HLT')
                op_p.scope = "ENTRY"; op_p.slot = "mdf2"
                op_p.character_id = character_id; op_p.entry_id = entry_id
                if cur:
                    op_c = row.operator("dmc5.clear_entry_binding", text="", icon='X')
                    op_c.character_id = character_id; op_c.entry_id = entry_id; op_c.suffix = "mdf2"

            if entry.get("chain"):
                head = entry_box.row(align=True)
                en = _get_enabled(scene, character_id, entry_id, "chain", entry_default)
                op = head.operator("dmc5.toggle_entry", text="",
                                   icon='CHECKBOX_HLT' if en else 'CHECKBOX_DEHLT', emboss=False)
                op.character_id = character_id; op.entry_id = entry_id; op.suffix = "chain"
                op.default_enabled = entry_default
                cur = _get_binding(scene, character_id, entry_id, "chain")
                ic = 'CONSTRAINT_BONE'
                if cur and cur in bpy.data.collections:
                    ct = bpy.data.collections[cur].color_tag
                    if ct != "NONE":
                        ic = f"COLLECTION_{ct}"
                chain_val = entry["chain"]
                chain_count = len(chain_val) if isinstance(chain_val, list) else 1
                head.label(text=(f"Chain x{chain_count}" if chain_count > 1 else "Chain"), icon=ic)
                row = entry_box.row(align=True)
                op_p = row.operator("dmc5.pick_binding",
                                    text=cur if cur else "Select...", icon='DOWNARROW_HLT')
                op_p.scope = "ENTRY"; op_p.slot = "chain"
                op_p.character_id = character_id; op_p.entry_id = entry_id
                if cur:
                    op_c = row.operator("dmc5.clear_entry_binding", text="", icon='X')
                    op_c.character_id = character_id; op_c.entry_id = entry_id; op_c.suffix = "chain"

            if entry.get("fbxskel"):
                row = entry_box.row(align=True)
                head = row.row(align=True)
                head.label(text="FBXSKEL", icon='ARMATURE_DATA')
                cur = _get_binding(scene, character_id, entry_id, "fbxskel")
                op_p = row.operator("dmc5.pick_armature",
                                    text=cur if cur else "Select fbxskel armature...", icon='DOWNARROW_HLT')
                op_p.character_id = character_id; op_p.entry_id = entry_id
                if cur:
                    op_c = row.operator("dmc5.clear_entry_binding", text="", icon='X')
                    op_c.character_id = character_id; op_c.entry_id = entry_id; op_c.suffix = "fbxskel"

    def execute(self, context):
        bpy.ops.dmc5.batch_export()
        return {'FINISHED'}


classes = [
    DMC5_GroupListItem,
    DMC5_UL_Groups,
    DMC5_OT_PickArmature,
    DMC5_OT_PickBinding,
    DMC5_OT_ToggleEntry,
    DMC5_OT_ClearEntryBinding,
    DMC5_OT_BatchExportDialog,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
