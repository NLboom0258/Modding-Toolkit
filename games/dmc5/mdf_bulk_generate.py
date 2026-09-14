"""Generate one MDF material per mesh material name, from a selected template material.

Why this exists
---------------
Wiring up an MDF2 for a mod means every submesh in the mesh collection needs a
material whose ``materialName`` matches it exactly.  Doing that by hand is
copy-paste + rename per material, which for a character split into a dozen
pieces is the slowest part of the job -- and the one with the least thinking in
it.

So: pick the material that already looks right (correct MMTR, flags,
properties, texture bindings -- whatever the starting point is), point this at
the mesh collection, and it becomes one copy per material name.

The template material is a *blueprint*: the mdf collection's existing materials
are replaced by the generated ones (the template's own name is not kept), which
is what "rebuild the material list from this one" means.
"""

import bpy

from ...core.i18n import T
from ...core.mesh_utils import material_name_of


_mesh_collection_items_cache = []


def mesh_collection_items(self, context):
    """Every RE mesh collection, as generation targets.

    Kept in a module-level list: Blender holds the pointers a dynamic ``items=``
    callback returns, so the strings have to stay referenced (the same fix the
    presets and bone pickers need).
    """
    global _mesh_collection_items_cache
    _mesh_collection_items_cache = [
        (coll.name, coll.name, "")
        for coll in sorted(bpy.data.collections, key=lambda c: c.name)
        if coll.get("~TYPE") == "RE_MESH_COLLECTION" or coll.name.endswith(".mesh")
    ]
    if not _mesh_collection_items_cache:
        _mesh_collection_items_cache = [("NONE", T("dmc5.mdf_bulk.no_collection_item"), "")]
    return _mesh_collection_items_cache


def collect_material_names(mesh_collection):
    """Unique material names used by *mesh_collection*'s meshes, in object-name order.

    Same precedence the exporter applies (``__`` suffix first, then the object's
    first Blender material), and de-duplicated: two submeshes sharing one
    material name share one MDF material, exactly as they share one
    ``materialIndex`` in the exported mesh.
    """
    names = []
    seen = set()
    meshes = sorted((obj for obj in mesh_collection.all_objects if obj.type == 'MESH'),
                    key=lambda obj: obj.name)
    for obj in meshes:
        name = material_name_of(obj)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def mdf_collection_of(obj):
    """The ``RE_MDF_COLLECTION`` *obj* belongs to, or None."""
    for coll in obj.users_collection:
        if coll.get("~TYPE") == "RE_MDF_COLLECTION":
            return coll
    return None


def rebuild_materials(template, mdf_collection, material_names):
    """Replace every material in *mdf_collection* with one copy of *template* per name.

    Copies first and deletes second, so the template can never be removed before
    its last copy exists.  Setting ``materialName`` renames the object through
    the property group's own update callback, so the final numbering pass runs
    afterwards to pin "Material NN (name)" regardless of where the name came
    from.
    """
    existing = [obj for obj in mdf_collection.all_objects
                if obj.get("~TYPE") == "RE_MDF_MATERIAL"]

    created = []
    for name in material_names:
        duplicate = template.copy()
        mdf_collection.objects.link(duplicate)
        created.append((duplicate, name))

    # The template is one of ``existing``, so it goes with the rest -- the copies
    # above are the only materials left afterwards.
    for obj in existing:
        bpy.data.objects.remove(obj, do_unlink=True)

    for duplicate, name in created:
        duplicate.re_mdf_material.materialName = name
    for index, (duplicate, _name) in enumerate(created):
        duplicate.name = f"Material {index:02d} ({duplicate.re_mdf_material.materialName})"
    return created


class DMC5_OT_MdfBulkGenerate(bpy.types.Operator):
    """Generate one MDF material per material name in a mesh collection, by copying the selected template material. The mdf collection's existing materials are replaced."""

    bl_idname = "dmc5.mdf_bulk_generate"
    bl_label = "Generate MDF Materials"
    bl_options = {'REGISTER', 'UNDO'}

    mesh_collection: bpy.props.EnumProperty(
        name="Mesh Collection",
        description="Mesh collection whose mesh material names the generated materials are named after",
        items=mesh_collection_items,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("~TYPE") == "RE_MDF_MATERIAL"

    def invoke(self, context, event):
        # Pre-fill when the mdf collection has a same-named mesh collection
        # (pl0500.mdf2 <-> pl0500.mesh) -- the common case when both came from
        # one import.
        template = context.active_object
        mdf_collection = mdf_collection_of(template) if template else None
        if mdf_collection is not None:
            guess = mdf_collection.name.replace(".mdf2", ".mesh")
            if guess in bpy.data.collections:
                self.mesh_collection = guess
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        template = context.active_object
        if template is None or template.get("~TYPE") != "RE_MDF_MATERIAL":
            self.report({'ERROR'}, T("dmc5.mdf_bulk.need_template"))
            return {'CANCELLED'}
        mdf_collection = mdf_collection_of(template)
        if mdf_collection is None:
            self.report({'ERROR'}, T("dmc5.mdf_bulk.no_mdf_collection"))
            return {'CANCELLED'}
        collection = bpy.data.collections.get(self.mesh_collection)
        if collection is None:
            self.report({'ERROR'}, T("dmc5.mdf_bulk.need_mesh_collection"))
            return {'CANCELLED'}

        names = collect_material_names(collection)
        if not names:
            self.report({'ERROR'}, T("dmc5.mdf_bulk.no_meshes"))
            return {'CANCELLED'}

        created = rebuild_materials(template, mdf_collection, names)
        self.report({'INFO'}, T("dmc5.mdf_bulk.done").format(count=len(created)))
        return {'FINISHED'}


classes = [
    DMC5_OT_MdfBulkGenerate,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
