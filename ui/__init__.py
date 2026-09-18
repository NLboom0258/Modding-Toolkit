from . import main_panel
from . import editor_panel
from . import name_cleanup
from . import personal_tools_panel

modules = [
    main_panel,
    editor_panel,
    name_cleanup,
    personal_tools_panel,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()
