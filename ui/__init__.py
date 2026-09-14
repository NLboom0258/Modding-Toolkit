from . import main_panel
from . import editor_panel
from . import name_cleanup

modules = [
    main_panel,
    editor_panel,
    name_cleanup,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()