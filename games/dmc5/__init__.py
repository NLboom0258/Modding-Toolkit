from . import shader_defs, mdf_tex_processor, mdf_tex_processor_ui, batch_export, batch_export_ui, mesh_rename


def register():
    mdf_tex_processor.register()
    mdf_tex_processor_ui.register()
    batch_export.register()
    batch_export_ui.register()
    mesh_rename.register()


def unregister():
    mesh_rename.unregister()
    batch_export_ui.unregister()
    batch_export.unregister()
    mdf_tex_processor_ui.unregister()
    mdf_tex_processor.unregister()
