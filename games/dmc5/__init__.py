from . import shader_defs, mdf_tex_processor, mdf_tex_processor_ui, batch_export, batch_export_ui, mdf_bulk_generate


def register():
    mdf_tex_processor.register()
    mdf_tex_processor_ui.register()
    batch_export.register()
    batch_export_ui.register()
    mdf_bulk_generate.register()


def unregister():
    mdf_bulk_generate.unregister()
    batch_export_ui.unregister()
    batch_export.unregister()
    mdf_tex_processor_ui.unregister()
    mdf_tex_processor.unregister()
