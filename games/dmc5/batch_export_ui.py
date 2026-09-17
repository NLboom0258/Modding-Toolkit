import bpy
from bpy.props import CollectionProperty, IntProperty, StringProperty

from .batch_export import (
    _load_scheme, _get_binding, _set_binding,
    _get_enabled, _set_enabled,
)

EXPORTER_WINDOW_WIDTH = 600

# 备注折行用。Blender 的 invoke_props_dialog 宽度只由 width 参数决定（内容超宽只会被
# 裁、不会把弹窗撑开），所以窗口宽度固定，靠折行保证每条备注都显示得下。
# 下面是 blf 实测的字符宽度表（Blender 默认 UI 字体，blf.size(0, 11)）：半角字符
# 宽度并不一致（l/i=3、s/_=6、0/h=7、A=8、M=10、W=11），按固定值估会整体偏宽 ——
# 那样每行会提前换行，靠“空格拼接”的缩进也会多出几像素。
_CHAR_PX = {
    " ": 3, "!": 3, '"': 5, "#": 7, "$": 7, "%": 11, "&": 7, "'": 3,
    "(": 4, ")": 4, "*": 7, "+": 7, ",": 3, "-": 7, ".": 3, "/": 4,
    "0": 7, "1": 7, "2": 7, "3": 7, "4": 7, "5": 7, "6": 7, "7": 7,
    "8": 7, "9": 7, ":": 3, ";": 3, "<": 7, "=": 7, ">": 7, "?": 6,
    "@": 11, "A": 8, "B": 7, "C": 8, "D": 8, "E": 7, "F": 7, "G": 8,
    "H": 8, "I": 5, "J": 6, "K": 8, "L": 6, "M": 10, "N": 8, "O": 8,
    "P": 7, "Q": 8, "R": 7, "S": 7, "T": 7, "U": 8, "V": 8, "W": 11,
    "X": 8, "Y": 8, "Z": 7, "[": 4, "\\": 4, "]": 4, "^": 5, "_": 6,
    "`": 4, "a": 6, "b": 7, "c": 6, "d": 7, "e": 6, "f": 4, "g": 7,
    "h": 7, "i": 3, "j": 4, "k": 6, "l": 3, "m": 10, "n": 7, "o": 7,
    "p": 7, "q": 7, "r": 4, "s": 6, "t": 4, "u": 7, "v": 6, "w": 9,
    "x": 6, "y": 6, "z": 6, "{": 4, "|": 4, "}": 4, "~": 7,
}
_PX_CJK = 11              # CJK/全角字符（实测基本等宽 11）
_PX_FALLBACK = 7          # 表里没有的字符（生僻半角/其他）按这个估
_DETAIL_PX = 340          # ui_scale=1 时详情列可用于文本的像素宽（600*0.65 - 余量）
_LIST_FACTOR = 0.35       # 左侧组列表占比（与 draw 里的 split factor 一致）


class _Metrics:
    """字符宽度度量。

    默认用内置的实测表（_CHAR_PX）；打开对话框时可以用 blf 现量一遍
    （见 _measure_metrics），这样用户改了界面字号 / DPI / 字体也能自动跟上。
    宽度单位统一是“ui_scale=1 时的像素”，与 _DETAIL_PX 同一个口径。
    """

    def __init__(self):
        self.ascii = dict(_CHAR_PX)
        self.cjk = float(_PX_CJK)
        self.fallback = float(_PX_FALLBACK)

    def char(self, ch):
        """单个字符的像素宽度。"""
        px = self.ascii.get(ch)
        if px is not None:
            return px
        return self.cjk if ord(ch) > 0x2E7F else self.fallback

    def text(self, s):
        """文本的像素宽度。"""
        return sum(self.char(ch) for ch in s)

    def wrap(self, s, max_px):
        """按像素宽度折行（中文没有空格可断，直接硬断）。"""
        lines, cur, cur_w = [], "", 0
        for ch in s:
            cw = self.char(ch)
            if cur and cur_w + cw > max_px:
                lines.append(cur)
                cur, cur_w = "", 0
            cur += ch
            cur_w += cw
        if cur:
            lines.append(cur)
        return lines or [""]


def _measure_metrics(context, scale):
    """用 Blender 自己的字体度量现量一遍字符宽度（量不到时返回内置表那份）。

    只在打开对话框时做一次：导出界面开着的时候用户改不了界面字号，
    所以这一次的度量整场有效。
    """
    metrics = _Metrics()
    try:
        import blf
        points = 11.0
        prefs = getattr(context, "preferences", None)
        styles = getattr(prefs, "ui_styles", None) if prefs is not None else None
        if styles is not None:
            points = float(getattr(styles[0].widget, "points", 11.0) or 11.0)
        blf.size(0, points * scale)
        for code in range(32, 127):
            ch = chr(code)
            metrics.ascii[ch] = blf.dimensions(0, ch)[0] / scale
        metrics.cjk = blf.dimensions(0, "中")[0] / scale
        metrics.fallback = metrics.ascii.get("n", metrics.fallback)
    except Exception:                                       # noqa: BLE001 - 量不到就用回内置表
        pass
    return metrics


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
        self._metrics_cache = None       # 首帧 draw 时用 blf 现量一次
        return context.window_manager.invoke_props_dialog(self, width=EXPORTER_WINDOW_WIDTH)

    def _get_metrics(self, context):
        """取字符宽度度量（首次调用时现量，之后整个对话框生命周期复用）。"""
        if self._metrics_cache is None:
            self._metrics_cache = _measure_metrics(
                context, getattr(self, "_ui_scale", 1.0) or 1.0)
        return self._metrics_cache

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
            self._draw_group_detail_normal(box, scene, character_id, selected_group,
                                           self._get_metrics(context))

    def _draw_group_detail_normal(self, layout, scene, character_id, group, metrics):
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
                # 可用像素折行（用实测字宽算）；续行缩进到备注文字的位置，缩进量随
                # id 长度变（用空格拼，实测每个空格 3px）。
                scale = getattr(self, "_ui_scale", 1.0) or 1.0
                avail = _DETAIL_PX / scale          # 高 DPI 下把可用宽度折算回基准像素
                prefix = f"{entry_id}  "
                indent_px = metrics.text(prefix)
                body = avail - indent_px
                if body < 40:                       # 装不下几个字：让 id 单独成行
                    entry_box.label(text=entry_id)
                    lines = metrics.wrap(note, max(40.0, avail))
                    indent, first_prefix = "", ""
                else:
                    lines = metrics.wrap(note, body)
                    indent = " " * max(1, int(indent_px / metrics.char(" ")))
                    first_prefix = prefix
                for _i, _ln in enumerate(lines):
                    entry_box.label(text=(first_prefix if _i == 0 else indent) + _ln)

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
