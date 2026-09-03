from . import shader_defs, mdf_tex_processor, mdf_tex_processor_ui


def register():
    mdf_tex_processor.register()
    mdf_tex_processor_ui.register()


def unregister():
    mdf_tex_processor_ui.unregister()
    mdf_tex_processor.unregister()
