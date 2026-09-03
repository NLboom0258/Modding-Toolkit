"""DMC5 (MDF2) packed shader specs — built from a real 3Dmigoto dump + real mdf2 materials.

Reference (user-provided): Dev! My Cry 5 "星见雅 mod 角色材质" pixel shader (ShaderFixes/...-ps.txt)
and the DMC5 mdf2 12-var materials (Env_Emissive.mmtr). Resource bindings + UserMaterial cbuffer:

  * BaseMetalMap (t1)              -- RGB = base colour, A = metallic (multiplied by VAR_Metallic).
  * NormalRoughnessMap (t2)        -- RGB = tangent-space normal (*2-1, reconstruct Z), A = roughness (x VAR_Roughness).
  * AlphaTranslucentOcclusionEmissiveMap (t3, "ATOS")
                                   -- R = alpha, G = translucency, B = ambient occlusion, A = Emissive intensity.

Shader outputs (confirmed):
  * o0 (HDR/emissive)  = ATOS.A x BaseMetalMap.rgb x VAR_EmissiveColor
                         i.e. the *base-colour texture RGB* is fed straight into emissive colour,
                         scaled by the ATOS.A mask and VAR_EmissiveColor tint.
  * o1 (albedo)        = BaseMetalMap.rgb x VAR_BaseColor
  * o2 (gbuffer)       = normal (NRMap.rgb*2-1) + roughness (NRMap.A x VAR_Roughness) + metallic (BaseMetalMap.A x VAR_Metallic)

The same "use base colour for emissive + ATOS.A as intensity" pattern is what the module docstring
in games/re9/shader_defs.py warns matters: only add bindings a real compiled shader carries.
This spec models the Env_Emissive archetype only; archetype-specific shader_03/EmissiveMap slots
are deferred until the DMC5 mdf2 materials that carry them are inspected.
"""

from ...core.shader_pack import (
    ShaderPackSpec, SlotSocket, PBRSocket, ALPHA_SUFFIX,
)

_K = "dmc5.shader_defs."

_FLAT = 0.5

# ── Core slots ────────────────────────────────────────────────────────────────

# BaseMetalMap: RGB colour + A metallic (multiplied against the panel's Metallic).
_BML = SlotSocket("BaseMetalMap", "core.shader_pack.albd",
                  default_color=(1.0, 1.0, 1.0, 1.0), alpha=True, default_alpha=1.0,
                  supplies=('color', 'metallic'), non_color=False)

# NormalRoughnessMap: plain tangent-space normal in RGB, roughness in A.
_NRM = SlotSocket("NormalRoughnessMap", "core.shader_pack.nrm",
                  default_color=(0.5, 0.5, 1.0, 1.0), alpha=True, default_alpha=1.0,
                  supplies=('normal', 'roughness'))

# ATOS: R alpha, G translucency, B AO, A Emissive intensity.
_ATOS = SlotSocket("AlphaTranslucentOcclusionEmissiveMap", _K + "atos",
                   default_color=(1.0, 0.0, 0.0, 0.0), alpha=True, default_alpha=1.0,
                   supplies=('alpha', 'ao', 'translucency', 'emissive'))

SLOTS_CORE = (_BML, _NRM, _ATOS)


# ── Inert secondary slots: carried through untouched (filled per real mdf2 as inspected) ──

def _inert(name, default_color=(1.0, 1.0, 1.0, 1.0), non_color=True):
    return SlotSocket(name, _K + name.lower(), default_color=default_color,
                      non_color=non_color, display=False)


SLOTS = SLOTS_CORE


# ── Scattered PBR inputs ───────────────────────────────────────────────────────

PBR = (
    PBRSocket("Base Color", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0),
              _K + "pbr_base_color", pbr_type='color', non_color=False),
    PBRSocket("Alpha", 'NodeSocketFloat', 1.0, _K + "pbr_alpha",
              min_value=0.0, max_value=1.0, subtype='FACTOR', pbr_type='alpha'),
    PBRSocket("Roughness", 'NodeSocketFloat', 1.0, _K + "pbr_roughness",
              min_value=0.0, max_value=1.0, subtype='FACTOR', pbr_type='roughness'),
    PBRSocket("Metallic", 'NodeSocketFloat', 0.0, _K + "pbr_metallic",
              min_value=0.0, max_value=1.0, subtype='FACTOR', pbr_type='metallic'),
    PBRSocket("AO", 'NodeSocketColor', (1.0, 1.0, 1.0, 1.0),
              _K + "pbr_ao", pbr_type='ao'),
    PBRSocket("Cavity", 'NodeSocketFloat', 1.0, _K + "pbr_cavity",
              min_value=0.0, max_value=1.0, subtype='FACTOR', pbr_type='cavity'),
    PBRSocket("Emission", 'NodeSocketColor', (0.0, 0.0, 0.0, 1.0),
              _K + "pbr_emission", pbr_type='emissive', non_color=False),
    PBRSocket("Emission Strength", 'NodeSocketFloat', 1.0,
              "core.shader_pack.pbr_emission_strength",
              min_value=0.0, max_value=9999.0),
    PBRSocket("Normal", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0),
              _K + "pbr_normal", pbr_type='normal'),
    PBRSocket("Translucency", 'NodeSocketFloat', 0.0, _K + "pbr_translucency",
              min_value=0.0, max_value=1.0, subtype='FACTOR', pbr_type='translucency'),
)


def _wire_normal_roughness_plain(b, row):
    """NRMap R/G is a plain 2-channel normal (reconstruct Z), roughness from A."""
    nrm_sep = b.separate(b.inp('NormalRoughnessMap'), col=1, row=row)
    slot_dr = b.math('SUBTRACT', nrm_sep.outputs[0], _FLAT, col=2, row=row)
    slot_dg = b.math('SUBTRACT', nrm_sep.outputs[1], _FLAT, col=2, row=row + 1)
    # Normal input is a colour; separate it the same way as the slot's own channels.
    pnr_sep = b.separate(b.inp('Normal'), col=1, row=row + 3)
    pbr_dr = b.math('SUBTRACT', pnr_sep.outputs[0], _FLAT, col=3, row=row + 3)
    pbr_dg = b.math('SUBTRACT', pnr_sep.outputs[1], _FLAT, col=3, row=row + 4)

    sum_r = b.math('ADD', slot_dr.outputs['Value'], pbr_dr.outputs['Value'], col=4, row=row)
    sum_g = b.math('ADD', slot_dg.outputs['Value'], pbr_dg.outputs['Value'], col=4, row=row + 1)
    r = b.math('ADD', sum_r.outputs['Value'], _FLAT, col=5, row=row)
    g = b.math('ADD', sum_g.outputs['Value'], _FLAT, col=5, row=row + 1)

    x = b.math('MULTIPLY_ADD', r.outputs['Value'], 2.0, col=6, row=row)
    x.inputs[2].default_value = -1.0
    y = b.math('MULTIPLY_ADD', g.outputs['Value'], 2.0, col=6, row=row + 1)
    y.inputs[2].default_value = -1.0
    xx = b.math('MULTIPLY', x.outputs['Value'], x.outputs['Value'], col=7, row=row)
    yy = b.math('MULTIPLY', y.outputs['Value'], y.outputs['Value'], col=7, row=row + 1)
    xxyy = b.math('ADD', xx.outputs['Value'], yy.outputs['Value'], col=8, row=row)
    zsq = b.math('SUBTRACT', 1.0, xxyy.outputs['Value'], clamp=True, col=9, row=row)
    z = b.math('SQRT', zsq.outputs['Value'], col=10, row=row)
    zenc = b.math('MULTIPLY_ADD', z.outputs['Value'], 0.5, col=11, row=row)
    zenc.inputs[2].default_value = 0.5

    ncomb = b.combine(r.outputs['Value'], g.outputs['Value'],
                      zenc.outputs['Value'], col=12, row=row)
    nmap = b.node('ShaderNodeNormalMap', col=13, row=row)
    nmap.inputs['Strength'].default_value = 1.0
    b.link(ncomb.outputs[0], nmap.inputs['Color'])
    b.link(nmap.outputs['Normal'], b.bsdf_in('Normal'))

    rough = b.math('MULTIPLY', b.inp('NormalRoughnessMap' + ALPHA_SUFFIX),
                   b.inp('Roughness'), clamp=True, col=1, row=row + 8)
    b.link(rough.outputs['Value'], b.bsdf_in('Roughness'))


def _wire_env_emissive(b):
    b.column(1)

    # albedo = BaseMetalMap.rgb x BaseColor
    base = b.mix('MULTIPLY', b.inp('BaseMetalMap'), b.inp('Base Color'))

    # metallic = BaseMetalMap.A x Metallic (direct multiply, per the dump)
    metal = b.math('MULTIPLY', b.inp('BaseMetalMap' + ALPHA_SUFFIX),
                   b.inp('Metallic'), clamp=True, col=1, row=4)
    b.link(metal.outputs['Value'], b.bsdf_in('Metallic'))

    # alpha = ATOS.R x Alpha
    atos_sep = b.separate(b.inp('AlphaTranslucentOcclusionEmissiveMap'), col=1, row=1)
    alpha = b.math('MULTIPLY', atos_sep.outputs[0], b.inp('Alpha'),
                   clamp=True, col=2, row=3)
    b.link(alpha.outputs['Value'], b.bsdf_in('Alpha'))

    # AO = ATOS.B
    ao_slot = b.mix('MULTIPLY', atos_sep.outputs[2], b.inp('AO'), col=2, row=1)
    # translucency = ATOS.G (carried as a round-trip socket; Principled has no matching input)
    transl = b.math('MULTIPLY', atos_sep.outputs[1], b.inp('Translucency'), clamp=True, col=2, row=7)

    # emissive = ATOS.A x BaseMetalMap.rgb x Emission colour
    emi_col = b.mix('MULTIPLY', b.inp('BaseMetalMap'), b.inp('Emission'), col=1, row=20)
    emi = b.mix('MULTIPLY', atos_sep.outputs[3], emi_col.outputs['Color'], col=2, row=20)
    b.link(emi.outputs['Color'], b.bsdf_in('Emission Color', 'Emission'))
    b.link(b.inp('Emission Strength'), b.bsdf_in('Emission Strength'))

    # normal + roughness
    _wire_normal_roughness_plain(b, row=8)

    shaded = b.mix('MULTIPLY', base.outputs['Color'], ao_slot.outputs['Color'], col=4, row=0)
    b.link(shaded.outputs['Color'], b.bsdf_in('Base Color'))


SPEC_ENV_EMISSIVE = ShaderPackSpec(
    group_name    = "MTK DMC5 EnvEmissive",
    shader_id     = "dmc5_env_emissive_v1",
    pbr_panel_key = "core.shader_pack.panel_pbr",
    slot_panel_key= "core.shader_pack.panel_slots_standard",
    pbr           = PBR,
    slots         = SLOTS,
    wire          = _wire_env_emissive,
    preset_filename = "env_emissive.json",
)


# ── Extra slots: ATOS-SSS (Standard) + inert TimeLock / RenderTarget ──────────

# ATOS-SSS: R alpha, G translucency, B AO, A SSS.
_ATOS_SSS = SlotSocket("AlphaTranslucentOcclusionSSSMap", _K + "atosss",
                       default_color=(1.0, 0.0, 1.0, 1.0), alpha=True, default_alpha=1.0,
                       supplies=('alpha', 'ao', 'translucency'))
# Inert: TimeLock 时停自发光 + RenderTarget (em6000/MajinBody). display=False so it
# round-trips to the exporter untouched; PBR panel Emission handles emissive manually
# (3-colour / Animation / TimeLock are runtime FX beyond a single-value PBR combiner).
_TIMELOCK = SlotSocket("TimeLock_EmissiveColor", _K + "timelock",
                       default_color=(0.0, 0.0, 0.0, 1.0), display=False)
_RENDERTGT = SlotSocket("RenderTarget", _K + "rendertarget",
                        default_color=(1.0, 1.0, 1.0, 1.0), display=False)


def _wire_standard(b):
    """em6000/MajinBody: PBR body (albedo/metallic/roughness/normal) + AO/alpha from ATOS-SSS.
    TimeLock_EmissiveColor / RenderTarget / 3-colour emissive / Animation are runtime FX
    -> left as inert slots, emissive handled manually via the PBR panel."""
    b.column(1)
    base = b.mix('MULTIPLY', b.inp('BaseMetalMap'), b.inp('Base Color'))

    metal = b.math('MULTIPLY', b.inp('BaseMetalMap' + ALPHA_SUFFIX),
                   b.inp('Metallic'), clamp=True, col=1, row=4)
    b.link(metal.outputs['Value'], b.bsdf_in('Metallic'))

    atos_sep = b.separate(b.inp('AlphaTranslucentOcclusionSSSMap'), col=1, row=1)
    alpha = b.math('MULTIPLY', atos_sep.outputs[0], b.inp('Alpha'),
                   clamp=True, col=2, row=3)
    b.link(alpha.outputs['Value'], b.bsdf_in('Alpha'))
    ao_slot = b.mix('MULTIPLY', atos_sep.outputs[2], b.inp('AO'), col=2, row=1)

    _wire_normal_roughness_plain(b, row=8)

    shaded = b.mix('MULTIPLY', base.outputs['Color'], ao_slot.outputs['Color'], col=4, row=0)
    b.link(shaded.outputs['Color'], b.bsdf_in('Base Color'))

    b.link(b.inp('Emission'), b.bsdf_in('Emission Color', 'Emission'))
    b.link(b.inp('Emission Strength'), b.bsdf_in('Emission Strength'))


SPEC_STANDARD = ShaderPackSpec(
    group_name    = "MTK DMC5 Standard",
    shader_id     = "dmc5_standard_v1",
    pbr_panel_key = "core.shader_pack.panel_pbr",
    slot_panel_key= "core.shader_pack.panel_slots_standard",
    pbr           = PBR,
    slots         = (_BML, _NRM, _ATOS_SSS, _TIMELOCK, _RENDERTGT),
    wire          = _wire_standard,
)

SPEC_GENERIC = ShaderPackSpec(
    group_name    = "MTK DMC5 Generic",
    shader_id     = "dmc5_generic_v1",
    pbr_panel_key = "core.shader_pack.panel_pbr",
    slot_panel_key= "core.shader_pack.panel_slots_standard",
    pbr           = PBR,
    slots         = (_BML, _NRM, _ATOS, _TIMELOCK, _RENDERTGT),
    wire          = _wire_env_emissive,
)

#: Registry for core/shader_ops.py -- one "game" ident per archetype.
VARIANTS = {
    'DMC5_ENV_EMISSIVE': SPEC_ENV_EMISSIVE,
    'DMC5_STANDARD': SPEC_STANDARD,
    'DMC5_GENERIC': SPEC_GENERIC,
}
