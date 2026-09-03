from . import mhwi, mhws, mhrs, re4, re9, dmc5

modules = [
    mhwi,
    mhws,
    mhrs,
    re4,
    re9,
    dmc5,
]

def register():
    for mod in modules:
        mod.register()

def unregister():
    for mod in reversed(modules):
        mod.unregister()