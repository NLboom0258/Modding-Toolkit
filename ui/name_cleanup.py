"""Non-ASCII bone / vertex-group cleanup.

RE Engine reads its mesh name table one byte at a time (RE Mesh Editor's
``read_string``), so a multi-byte character in a bone, vertex-group or material
name makes the exported mesh impossible to re-import -- and the game's own
skeletons are ASCII throughout.  MMD-derived rigs arrive full of Japanese bone
names, and nothing in Blender lists them, so this section does.

Bones (in the armature) and vertex groups (on each mesh) are independent data
that the Armature modifier pairs by *name* alone, so both sides are listed
under the name they share.
"""

import bpy

from ..core.i18n import T


def bound_meshes(armature):
    """Mesh objects skinned to *armature* through an Armature modifier."""
    return [obj for obj in bpy.data.objects
            if obj.type == 'MESH'
            and any(mod.type == 'ARMATURE' and mod.object == armature
                    for mod in obj.modifiers)]


def collect_non_ascii(armature):
    """``[(name, in_bones, in_vertex_groups)]`` for every non-ASCII name, sorted."""
    in_bones = set()
    in_groups = set()
    for bone in armature.data.bones:
        if not bone.name.isascii():
            in_bones.add(bone.name)
    for obj in bound_meshes(armature):
        for group in obj.vertex_groups:
            if not group.name.isascii():
                in_groups.add(group.name)
    return [(name, name in in_bones, name in in_groups)
            for name in sorted(in_bones | in_groups)]


def rename_everywhere(armature, old_name, new_name):
    """Rename the bone -- the vertex groups follow -- or a lone vertex group.

    Renaming a bone makes Blender itself update the vertex groups that
    reference it, so the groups on skinned meshes come along.  The second pass
    is for a name that only ever existed as a vertex group: nothing pairs it to
    a bone, so nothing else would rename it.
    """
    bone = armature.data.bones.get(old_name)
    if bone is not None:
        bone.name = new_name
    for obj in bound_meshes(armature):
        group = obj.vertex_groups.get(old_name)
        if group is not None:
            group.name = new_name


def remove_vertex_groups(armature, name):
    """Drop every vertex group called *name* on the skinned meshes."""
    for obj in bound_meshes(armature):
        group = obj.vertex_groups.get(name)
        if group is not None:
            obj.vertex_groups.remove(group)


def remove_bone_reconnect(armature, bone_name):
    """Delete a bone in edit mode, re-parenting its children to its parent.

    Returns ``(child_count, parent_name)``; *parent_name* is None when the bone
    was a root, in which case its children become roots themselves.
    """
    if armature.data.bones.get(bone_name) is None:
        return 0, None

    if armature.hide_viewport:
        armature.hide_viewport = False
    try:
        if armature.hide_get():
            armature.hide_set(False)
    except Exception:
        pass

    bpy.context.view_layer.objects.active = armature
    toggled = armature.mode != 'EDIT'
    if toggled:
        bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = armature.data.edit_bones
    edit_bone = edit_bones.get(bone_name)
    child_count = 0
    parent_name = None
    if edit_bone is not None:
        parent = edit_bone.parent
        parent_name = parent.name if parent is not None else None
        children = list(edit_bone.children)
        child_count = len(children)
        for child in children:
            # Disconnect before re-parenting: a connected child would otherwise
            # drag the new parent along with it.
            child.use_connect = False
            child.parent = parent
        edit_bones.remove(edit_bone)

    if toggled:
        bpy.ops.object.mode_set(mode='OBJECT')
    return child_count, parent_name


def merge_weights_into(armature, source_name, target_name):
    """Add every weight held by *source_name*'s groups onto *target_name*'s.

    The source groups are removed afterwards.  No normalisation or weight-count
    limit is applied: the caller's own finishing pass owns that.
    """
    for obj in bound_meshes(armature):
        source = obj.vertex_groups.get(source_name)
        if source is None:
            continue
        target = obj.vertex_groups.get(target_name)
        if target is None:
            target = obj.vertex_groups.new(name=target_name)

        source_index = source.index
        moved = []
        for vertex in obj.data.vertices:
            weight = 0.0
            for entry in vertex.groups:
                if entry.group == source_index:
                    weight += entry.weight
            if weight > 0.0:
                moved.append((vertex.index, weight))

        for index, weight in moved:
            target.add([index], weight, 'ADD')
        obj.vertex_groups.remove(source)


class MTK_OT_RenameNonAscii(bpy.types.Operator):
    """Rename a non-ASCII bone / vertex-group name to an ASCII one."""

    bl_idname = "mtk.rename_non_ascii"
    bl_label = "Rename"
    bl_options = {'REGISTER', 'UNDO'}

    old_name: bpy.props.StringProperty(options={'HIDDEN'})
    new_name: bpy.props.StringProperty(name="New Name")

    @classmethod
    def poll(cls, context):
        armature = context.active_object
        return armature is not None and armature.type == 'ARMATURE'

    def invoke(self, context, event):
        self.new_name = self.old_name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        armature = context.active_object
        new_name = self.new_name.strip()

        if not new_name:
            self.report({'ERROR'}, T("mtk.name_cleanup.err_empty"))
            return {'CANCELLED'}
        if not new_name.isascii():
            self.report({'ERROR'}, T("mtk.name_cleanup.err_ascii"))
            return {'CANCELLED'}
        if new_name != self.old_name:
            if armature.data.bones.get(new_name) is not None:
                self.report({'ERROR'}, T("mtk.name_cleanup.err_bone_conflict").format(name=new_name))
                return {'CANCELLED'}
            for obj in bound_meshes(armature):
                if obj.vertex_groups.get(new_name) is not None:
                    self.report({'ERROR'}, T("mtk.name_cleanup.err_group_conflict").format(name=new_name))
                    return {'CANCELLED'}

        rename_everywhere(armature, self.old_name, new_name)
        self.report({'INFO'}, T("mtk.name_cleanup.renamed").format(old=self.old_name, new=new_name))
        return {'FINISHED'}


class MTK_OT_DeleteNonAscii(bpy.types.Operator):
    """Delete a non-ASCII bone (re-parenting its children) and its vertex groups."""

    bl_idname = "mtk.delete_non_ascii"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        armature = context.active_object
        return armature is not None and armature.type == 'ARMATURE'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event,
            title=T("mtk.name_cleanup.confirm_delete_title"),
            message=T("mtk.name_cleanup.confirm_delete_msg").format(name=self.name),
        )

    def execute(self, context):
        armature = context.active_object
        child_count, parent_name = remove_bone_reconnect(armature, self.name)
        remove_vertex_groups(armature, self.name)

        if parent_name is not None:
            self.report({'INFO'}, T("mtk.name_cleanup.deleted").format(
                name=self.name, count=child_count, parent=parent_name))
        else:
            self.report({'INFO'}, T("mtk.name_cleanup.deleted_root").format(
                name=self.name, count=child_count))
        return {'FINISHED'}


class MTK_OT_MergeNonAscii(bpy.types.Operator):
    """Merge a non-ASCII bone into its parent: its weights move to the parent's group."""

    bl_idname = "mtk.merge_non_ascii"
    bl_label = "Merge into Parent"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        armature = context.active_object
        return armature is not None and armature.type == 'ARMATURE'

    def invoke(self, context, event):
        armature = context.active_object
        bone = armature.data.bones.get(self.name)
        parent_name = bone.parent.name if (bone is not None and bone.parent is not None) else ""
        return context.window_manager.invoke_confirm(
            self, event,
            title=T("mtk.name_cleanup.confirm_merge_title"),
            message=T("mtk.name_cleanup.confirm_merge_msg").format(name=self.name, parent=parent_name),
        )

    def execute(self, context):
        armature = context.active_object
        bone = armature.data.bones.get(self.name)

        if bone is None:
            self.report({'ERROR'}, T("mtk.name_cleanup.err_no_bone").format(name=self.name))
            return {'CANCELLED'}
        if bone.parent is None:
            self.report({'ERROR'}, T("mtk.name_cleanup.err_no_parent").format(name=self.name))
            return {'CANCELLED'}

        parent_name = bone.parent.name
        merge_weights_into(armature, self.name, parent_name)
        remove_bone_reconnect(armature, self.name)
        self.report({'INFO'}, T("mtk.name_cleanup.merged").format(name=self.name, parent=parent_name))
        return {'FINISHED'}


class MTK_OT_SelectCleanupBone(bpy.types.Operator):
    """Select this bone in pose mode, to look at it in the viewport."""

    bl_idname = "mtk.select_cleanup_bone"
    bl_label = "Select Bone"
    bl_options = {'REGISTER'}

    name: bpy.props.StringProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        armature = context.active_object
        return armature is not None and armature.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        if armature.data.bones.get(self.name) is None:
            self.report({'ERROR'}, T("mtk.name_cleanup.err_no_bone").format(name=self.name))
            return {'CANCELLED'}

        if armature.hide_viewport:
            armature.hide_viewport = False
        try:
            if armature.hide_get():
                armature.hide_set(False)
        except Exception:
            pass

        bpy.context.view_layer.objects.active = armature
        armature.select_set(True)
        if armature.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')

        for pose_bone in armature.pose.bones:
            pose_bone.bone.select = False
        pose_bone = armature.pose.bones.get(self.name)
        if pose_bone is not None:
            pose_bone.bone.select = True
            armature.data.bones.active = armature.data.bones[self.name]

        self.report({'INFO'}, T("mtk.name_cleanup.selected").format(name=self.name))
        return {'FINISHED'}


def draw_name_cleanup(box, context):
    """Draw the section body into *box* (the main panel owns the header)."""
    armature = context.active_object

    if armature is None or armature.type != 'ARMATURE':
        box.label(text=T("ui.name_cleanup.no_armature"), icon='INFO')
        return

    settings = getattr(context.scene, "mhw_suite_settings", None)
    if settings is not None:
        box.row(align=True).prop(settings, "name_cleanup_filter", text="", icon='VIEWZOOM')

    entries = collect_non_ascii(armature)
    needle = settings.name_cleanup_filter.strip().lower() if settings is not None else ""
    if needle:
        entries = [entry for entry in entries if needle in entry[0].lower()]

    if not entries:
        box.label(text=T("ui.name_cleanup.none_after_filter") if needle
                  else T("ui.name_cleanup.all_ascii"), icon='CHECKMARK')
        return

    box.label(text=T("ui.name_cleanup.found").format(count=len(entries)), icon='ERROR')
    col = box.column(align=True)
    for name, in_bones, in_groups in entries:
        row = col.row(align=True)
        # A fixed split, not a spacer: a spacer depends on the row's leftover
        # space, which is not the same on every row (a row whose name only
        # exists as a bone draws one icon fewer), so the two icon columns used
        # to land in different places.  Splitting pins them.
        split = row.split(factor=0.45)
        split.label(text=name)
        right = split.row(align=True)
        # 'BLANK1' is Blender's blank placeholder icon -- same width as a real
        # one.  'NONE' would degrade the label to an empty text label, whose
        # width follows different rules and squeezed the buttons on rows that
        # only carry one side of the name.
        right.label(text="", icon='BONE_DATA' if in_bones else 'BLANK1')
        right.label(text="", icon='GROUP_VERTEX' if in_groups else 'BLANK1')

        select_row = right.row(align=True)
        select_row.enabled = in_bones
        op = select_row.operator("mtk.select_cleanup_bone", text="", icon='RESTRICT_SELECT_OFF')
        op.name = name

        op = right.operator("mtk.rename_non_ascii", text="", icon='FONT_DATA')
        op.old_name = name
        op = right.operator("mtk.delete_non_ascii", text="", icon='TRASH')
        op.name = name
        op = right.operator("mtk.merge_non_ascii", text="", icon='AUTOMERGE_ON')
        op.name = name


classes = [
    MTK_OT_RenameNonAscii,
    MTK_OT_DeleteNonAscii,
    MTK_OT_MergeNonAscii,
    MTK_OT_SelectCleanupBone,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
