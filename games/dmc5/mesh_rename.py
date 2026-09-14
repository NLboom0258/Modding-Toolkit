"""Rename selected meshes into RE Engine's ``Group_<N>_Sub_<M>__<material>`` form.

RE Engine's mesh file stores no object names at all -- only a viscon group
number, a submesh index and a material-name string.  RE Mesh Editor rebuilds
``Group_<N>_Sub_<M>__<material>`` out of those three on import, and parses the
same shape back on export -- where only ``Group_<N>`` (the group) and the text
after ``__`` (the material) are read; the ``Sub`` number is ignored there.

So renaming only normalizes the *name*, under two rules:

* objects are sorted by their **current name** -- the order the Outliner shows
  with "Sort Alphabetically" enabled.  That is stable; the collection's internal
  object order is not, since it changes whenever an object is added or removed.
* ``Sub`` is numbered from 0 within each ``Group_<N>`` (objects with no
  ``Group_`` in their name count as group 0).

No zero padding: RE Mesh Editor itself writes ``Sub_0``/``Sub_1``/... on import
and the community follows the same shape, and the game never reads this string.

Names must stay ASCII.  RE Mesh Editor's ``read_string`` decodes the mesh name
table one byte at a time as UTF-8, so a multi-byte (Japanese/Chinese) bone,
vertex-group or material name makes the exported mesh impossible to re-import.
"""

import re

import bpy

from ...core.i18n import T


_GROUP_RE = re.compile(r"Group_(\d+)")
_NO_MATERIAL = "NO_MATERIAL"


def parse_group_id(name):
    """Return the ``Group_<N>`` number in *name*, or 0 when it carries none."""
    match = _GROUP_RE.search(name)
    return int(match.group(1)) if match else 0


def material_name_of(obj):
    """Material name for *obj*.

    Same precedence RE Mesh Editor applies on export, in the same order: the
    text after ``__`` in the object name first, its first Blender material as
    the fallback, and a placeholder when neither is usable.
    """
    if "__" in obj.name:
        tail = obj.name.split("__", 1)[1].split(".")[0].strip()
        if tail:
            return tail
    if obj.data.materials:
        material = obj.data.materials[0]
        if material is not None:
            head = material.name.split(".")[0].strip()
            if head:
                return head
    return _NO_MATERIAL


def build_rename_plan(objects):
    """Return ``[(obj, new_name)]`` for *objects*, sorted by name, numbered per group."""
    counters = {}
    plan = []
    for obj in sorted(objects, key=lambda o: o.name):
        group_id = parse_group_id(obj.name)
        sub = counters.get(group_id, 0)
        counters[group_id] = sub + 1
        plan.append((obj, f"Group_{group_id}_Sub_{sub}__{material_name_of(obj)}"))
    return plan


def rename_mesh_objects(objects):
    """Apply :func:`build_rename_plan` in two passes and return the plan.

    The first pass parks every object on a unique temporary name, so a target
    name can never collide with an object that has not been renamed yet --
    Blender object names are unique, and a plan can legitimately reuse a name
    another object still holds.
    """
    plan = build_rename_plan(objects)
    for index, (obj, _new_name) in enumerate(plan):
        obj.name = f"__mtk_rename_tmp_{index}"
    for obj, new_name in plan:
        obj.name = new_name
    return plan


def mesh_collection_of(obj):
    """Return the ``RE_MESH_COLLECTION`` *obj* belongs to, or None."""
    for coll in obj.users_collection:
        if coll.get("~TYPE") == "RE_MESH_COLLECTION":
            return coll
    return None


class DMC5_OT_RenameMeshREFormat(bpy.types.Operator):
    """Rename selected meshes to Group_<N>_Sub_<M>__<material>: sorted by object name, numbered from Sub_0 within each Group_<N>, matching the names RE Mesh Editor writes on import. All selected meshes must be in one mesh collection, and object/bone/material names must stay ASCII."""

    bl_idname = "dmc5.rename_mesh_re_format"
    bl_label = "Rename Meshes (RE Format)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not meshes:
            self.report({'ERROR'}, T("dmc5.mesh_rename.need_selection"))
            return {'CANCELLED'}

        # One collection at a time.  Numbering restarts per group, so two
        # collections would both emit Group_0_Sub_0__..., and Blender's unique
        # object names would silently force a ".001" suffix onto the second.
        collections = {mesh_collection_of(obj) for obj in meshes}
        if len(collections) > 1:
            self.report({'ERROR'}, T("dmc5.mesh_rename.multi_collection"))
            return {'CANCELLED'}

        plan = rename_mesh_objects(meshes)
        self.report({'INFO'}, T("dmc5.mesh_rename.done").format(count=len(plan)))
        return {'FINISHED'}


classes = [
    DMC5_OT_RenameMeshREFormat,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
