"""
Procedural "Douyin influencer" style stylised female character for Blender.

Everything is generated from code: run it inside Blender's Text Editor
(Run Script), or headless:

    blender --background --python douyin_girl.py -- [--render] [--quick] [--out DIR]

or with the `bpy` pip module:

    python douyin_girl.py [--render] [--quick] [--out DIR]

The look follows common Douyin beauty-filter aesthetics: small V-shaped face,
big bright eyes with coloured contacts, aegyo-sal (卧蚕), double eyelids and
manga-style cluster lashes, a high slim nose bridge with a small upturned tip,
gradient "bitten" glossy lips, rosy blush, porcelain skin, long tea-brown hair
with curtain bangs, swan neck, slim waist and long legs in a white slip dress
and heels, lit by a ring light against a pastel backdrop in 9:16.
"""

import math
import os
import random
import sys

import bpy  # noqa: E402  (bpy must be imported before bmesh in the pip module)
import bmesh
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
DO_RENDER = "--render" in argv
QUICK = "--quick" in argv
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
if "--out" in argv:
    OUT_DIR = os.path.abspath(argv[argv.index("--out") + 1])
ONLY = None
if "--only" in argv:  # comma separated subset of shots: full,portrait,side
    ONLY = set(argv[argv.index("--only") + 1].split(","))

random.seed(7)

# Head is modelled in "head units" (1 unit = 10 cm) under an empty.
HEAD_POS = Vector((0.0, 0.0, 1.555))
HU = 0.1


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smoothstep(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


def gauss(x, z, cx, cz, rx, rz):
    return math.exp(-(((x - cx) / rx) ** 2 + ((z - cz) / rz) ** 2))


def lerp(a, b, t):
    return a + (b - a) * t


def mix3(a, b, t):
    return tuple(lerp(a[i], b[i], t) for i in range(3))


def srgb(hexstr):
    """'#RRGGBB' (sRGB) -> linear RGB tuple."""
    hexstr = hexstr.lstrip("#")
    out = []
    for i in range(3):
        c = int(hexstr[2 * i:2 * i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def mesh_object(name, bm, parent=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, parent)
    return obj


def shade_smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True


def add_subsurf(obj, view=1, render=2):
    m = obj.modifiers.new("Subdivision", "SUBSURF")
    m.levels = view
    m.render_levels = render
    return m


def bvh_of(objs, world=False):
    """BVH of the evaluated meshes of objs (local space of the first object
    unless world=True)."""
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        tmp = bmesh.new()
        tmp.from_mesh(me)
        if world:
            tmp.transform(o.matrix_world)
        elif o is not objs[0]:
            tmp.transform(objs[0].matrix_world.inverted() @ o.matrix_world)
        me2 = bpy.data.meshes.new("_tmp")
        tmp.to_mesh(me2)
        bm.from_mesh(me2)
        bpy.data.meshes.remove(me2)
        tmp.free()
        ev.to_mesh_clear()
    bm.verts.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree


def curve_object(name, strands, bevel, parent=None, resolution=3, mat=None,
                 cyclic=False, bevel_res=2):
    """strands: list of (points, radii). Builds one poly-spline curve object."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = bevel
    cu.bevel_resolution = bevel_res
    cu.resolution_u = resolution
    cu.use_fill_caps = True
    for pts, radii in strands:
        sp = cu.splines.new("NURBS")
        sp.points.add(len(pts) - 1)
        for i, (p, r) in enumerate(zip(pts, radii)):
            sp.points[i].co = (p[0], p[1], p[2], 1.0)
            sp.points[i].radius = r
        sp.order_u = min(4, len(pts))
        sp.use_endpoint_u = True
        sp.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    link(obj, parent)
    if mat:
        obj.data.materials.append(mat)
    return obj


# ---------------------------------------------------------------------------
# Scene reset
# ---------------------------------------------------------------------------

def reset_scene():
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.curves,
                 bpy.data.materials, bpy.data.metaballs, bpy.data.lights,
                 bpy.data.cameras, bpy.data.images):
        for item in list(coll):
            coll.remove(item)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

SKIN = srgb("#F5D3C4")
SKIN_SHADOW = srgb("#E8B3A0")
BLUSH = srgb("#F19C9E")
LIP_IN = srgb("#B8243F")
LIP_OUT = srgb("#EE8C92")
SHADOW_EYE = srgb("#D69486")
HIGHLIGHT = srgb("#FFF0EA")


def new_material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, mat.node_tree.nodes, mat.node_tree.links


def principled(mat_nodes):
    return mat_nodes.get("Principled BSDF")


def set_inputs(node, **kw):
    for k, v in kw.items():
        node.inputs[k.replace("_", " ")].default_value = v


def mat_skin(name="Skin", with_paint=False):
    mat, nodes, links = new_material(name)
    bsdf = principled(nodes)
    set_inputs(bsdf, Roughness=0.42, Subsurface_Weight=0.25,
               Subsurface_Scale=0.006, Specular_IOR_Level=0.45,
               Sheen_Weight=0.15)
    bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
    bsdf.inputs["Base Color"].default_value = (*SKIN, 1.0)
    if with_paint:
        col = nodes.new("ShaderNodeVertexColor")
        col.layer_name = "paint"
        links.new(col.outputs["Color"], bsdf.inputs["Base Color"])
        # lips: glossy
        gl = nodes.new("ShaderNodeAttribute")
        gl.attribute_name = "gloss"
        mr = nodes.new("ShaderNodeMapRange")
        mr.inputs["To Min"].default_value = 0.42
        mr.inputs["To Max"].default_value = 0.12
        links.new(gl.outputs["Fac"], mr.inputs["Value"])
        links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
        cw = nodes.new("ShaderNodeMapRange")
        cw.inputs["To Min"].default_value = 0.0
        cw.inputs["To Max"].default_value = 0.6
        links.new(gl.outputs["Fac"], cw.inputs["Value"])
        links.new(cw.outputs["Result"], bsdf.inputs["Coat Weight"])
    return mat


def mat_simple(name, color, rough=0.5, **kw):
    mat, nodes, links = new_material(name)
    bsdf = principled(nodes)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    set_inputs(bsdf, **kw)
    return mat


def mat_emit(name, color, strength):
    mat, nodes, links = new_material(name)
    bsdf = principled(nodes)
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
    bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def mat_iris():
    """Coloured-contact iris: radial gradient with fibres, dark limbal ring."""
    mat, nodes, links = new_material("Iris")
    bsdf = principled(nodes)
    set_inputs(bsdf, Roughness=0.25, Coat_Weight=1.0, Coat_Roughness=0.02)
    tc = nodes.new("ShaderNodeTexCoord")
    grad = nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "SPHERICAL"
    links.new(tc.outputs["Object"], grad.inputs["Vector"])
    # radial fibres
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Object"], sep.inputs["Vector"])
    ang = nodes.new("ShaderNodeMath")
    ang.operation = "ARCTAN2"
    links.new(sep.outputs["Z"], ang.inputs[0])
    links.new(sep.outputs["X"], ang.inputs[1])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    noise.inputs["Detail"].default_value = 4.0
    comb = nodes.new("ShaderNodeCombineXYZ")
    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 6.0
    links.new(ang.outputs[0], mul.inputs[0])
    links.new(mul.outputs[0], comb.inputs["X"])
    links.new(grad.outputs["Fac"], comb.inputs["Y"])
    links.new(comb.outputs["Vector"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position = 0.0
    cr.elements[0].color = (*srgb("#2A1A14"), 1)
    cr.elements[1].position = 1.0
    cr.elements[1].color = (0.0, 0.0, 0.0, 1)
    for pos, hexc in ((0.10, "#3E2A20"), (0.20, "#8A6446"), (0.45, "#C99A6B"),
                      (0.62, "#A87A52"), (0.70, "#3A2418"), (0.735, "#050302")):
        e = cr.elements.new(pos)
        e.color = (*srgb(hexc), 1)
    # perturb radius with fibres
    add = nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    add.inputs[1].default_value = 0.10
    links.new(noise.outputs["Fac"], add.inputs[0])
    links.new(grad.outputs["Fac"], add.inputs[2])
    sub = nodes.new("ShaderNodeMath")
    sub.operation = "SUBTRACT"
    sub.inputs[1].default_value = 0.05
    links.new(add.outputs[0], sub.inputs[0])
    links.new(sub.outputs[0], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def mat_hair(name, melanin=0.62, redness=0.55, rough=0.32):
    mat, nodes, links = new_material(name)
    out = nodes.get("Material Output")
    nodes.remove(principled(nodes))
    hair = nodes.new("ShaderNodeBsdfHairPrincipled")
    hair.parametrization = "MELANIN"
    hair.inputs["Melanin"].default_value = melanin
    hair.inputs["Melanin Redness"].default_value = redness
    hair.inputs["Roughness"].default_value = rough
    hair.inputs["Radial Roughness"].default_value = 0.4
    hair.inputs["Coat"].default_value = 0.1
    # random per strand variation
    info = nodes.new("ShaderNodeHairInfo")
    mr = nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = melanin - 0.06
    mr.inputs["To Max"].default_value = melanin + 0.06
    links.new(info.outputs["Random"], mr.inputs["Value"])
    links.new(mr.outputs["Result"], hair.inputs["Melanin"])
    links.new(hair.outputs[0], out.inputs["Surface"])
    return mat


def mat_dress():
    """Soft satin white for the slip dress."""
    mat, nodes, links = new_material("Dress")
    bsdf = principled(nodes)
    set_inputs(bsdf, Roughness=0.33, Sheen_Weight=0.6, Sheen_Roughness=0.3,
               Specular_IOR_Level=0.6, Anisotropic=0.4)
    bsdf.inputs["Base Color"].default_value = (*srgb("#F5F1EE"), 1)
    bsdf.inputs["Sheen Tint"].default_value = (*srgb("#FFE6EA"), 1)
    return mat


def mat_body():
    """Skin with object-space masks for dress (body) and heels (feet)."""
    mat, nodes, links = new_material("BodySkin")
    out = nodes.get("Material Output")
    skin = principled(nodes)
    set_inputs(skin, Roughness=0.42, Subsurface_Weight=0.25,
               Subsurface_Scale=0.008, Specular_IOR_Level=0.45,
               Sheen_Weight=0.15)
    skin.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
    skin.inputs["Base Color"].default_value = (*SKIN, 1.0)

    dress = nodes.new("ShaderNodeBsdfPrincipled")
    set_inputs(dress, Roughness=0.33, Sheen_Weight=0.6, Sheen_Roughness=0.3,
               Specular_IOR_Level=0.6)
    dress.inputs["Base Color"].default_value = (*srgb("#F5F1EE"), 1)

    shoe = nodes.new("ShaderNodeBsdfPrincipled")
    set_inputs(shoe, Roughness=0.18, Coat_Weight=0.8)
    shoe.inputs["Base Color"].default_value = (*srgb("#E7C2AE"), 1)

    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Object"], sep.inputs["Vector"])

    def band(lo, hi, soft=0.004):
        a = nodes.new("ShaderNodeMapRange")
        a.inputs["From Min"].default_value = lo - soft
        a.inputs["From Max"].default_value = lo + soft
        links.new(sep.outputs["Z"], a.inputs["Value"])
        b = nodes.new("ShaderNodeMapRange")
        b.inputs["From Min"].default_value = hi + soft
        b.inputs["From Max"].default_value = hi - soft
        links.new(sep.outputs["Z"], b.inputs["Value"])
        m = nodes.new("ShaderNodeMath")
        m.operation = "MULTIPLY"
        links.new(a.outputs["Result"], m.inputs[0])
        links.new(b.outputs["Result"], m.inputs[1])
        return m.outputs[0]

    mix1 = nodes.new("ShaderNodeMixShader")
    links.new(band(DRESS_HEM, DRESS_TOP), mix1.inputs["Fac"])
    links.new(skin.outputs[0], mix1.inputs[1])
    links.new(dress.outputs[0], mix1.inputs[2])
    mix2 = nodes.new("ShaderNodeMixShader")
    links.new(band(-1.0, SHOE_TOP, 0.003), mix2.inputs["Fac"])
    links.new(mix1.outputs[0], mix2.inputs[1])
    links.new(shoe.outputs[0], mix2.inputs[2])
    links.new(mix2.outputs[0], out.inputs["Surface"])
    return mat


DRESS_HEM = 0.60
DRESS_TOP = 1.255
SHOE_TOP = 0.085


# ---------------------------------------------------------------------------
# Head
# ---------------------------------------------------------------------------

EYE_CX = 0.315    # eye centre (head units, |x|)
EYE_CZ = -0.07
EYE_A = 0.175     # half width
EYE_HU = 0.10     # upper lid height
EYE_HL = 0.062    # lower lid height
EYE_LIFT = 0.022  # outer corner lift
EYE_DEPTH = 0.16

MOUTH_Z = -0.575


def eye_upper(u):
    """Upper lid curve height above the eye centre line at u in [-1, 1]."""
    u = clamp(u, -1, 1)
    # peak slightly towards the inner side, rounder in the middle
    return EYE_HU * (1 - u * u) ** 0.62 * (1.0 - 0.12 * u)


def eye_lower(u):
    u = clamp(u, -1, 1)
    return EYE_HL * (1 - u * u) ** 0.75 * (1.0 + 0.15 * u)


def eye_center_z(u):
    return EYE_CZ + EYE_LIFT * u


def eye_metric(X, Z):
    """< 1 inside the almond-shaped eye opening."""
    u = (abs(X) - EYE_CX) / EYE_A
    dz = Z - eye_center_z(u)
    if abs(u) >= 1.0:
        h = 0.02
    else:
        h = eye_upper(u) if dz > 0 else eye_lower(u)
        h = max(h, 0.012)
    return u * u + (dz / h) ** 2 * (1.0 if abs(u) < 1 else 4.0)


def lip_bounds(x):
    """(lower lip bottom, mouth line, upper lip top) at x."""
    w_up, w_lo = 0.185, 0.165
    zm = MOUTH_Z + 0.18 * x * x
    au = clamp(1 - (x / w_up) ** 2)
    al = clamp(1 - (x / w_lo) ** 2)
    zu = zm + 0.072 * au ** 0.65 - 0.014 * math.exp(-(x / 0.035) ** 2) * au
    # cupid's bow peaks
    zu += 0.008 * math.exp(-((abs(x) - 0.05) / 0.03) ** 2)
    zl = zm - 0.088 * al ** 0.55
    return zl, zm, zu


def head_base(p):
    """Map a unit-sphere direction to the (eye-less) head surface."""
    x, y, z = p
    # Fuller, flatter lower-front of the face (superellipse blend)
    n = 2.7
    k = (abs(x) ** n + abs(y) ** n + abs(z) ** n) ** (1.0 / n)
    w = smoothstep(0.0, 0.55, -y) * smoothstep(-0.25, 0.35, -z)
    s = 1.0 + w * (1.0 / k - 1.0) * 0.85
    x, y, z = x * s, y * s, z * s

    X, Y, Z = 0.80 * x, 0.93 * y, 1.04 * z

    # V-line jaw: taper the lower head towards a small rounded chin
    t = clamp((0.05 - Z) / 1.1)
    X *= 1.0 - 0.43 * t ** 1.45
    if Y > 0:  # back of the lower head tucks in towards the neck
        Y *= 1.0 - 0.55 * smoothstep(0.1, 0.9, t)
    else:
        Y *= 1.0 - 0.10 * smoothstep(0.55, 1.0, t)
    # chin a touch longer & softly pointed
    if Z < 0:
        Z *= 0.93
    if Z < -0.70:
        Z -= 0.05 * smoothstep(-0.70, -0.98, Z) * (1 - min(1, abs(X) / 0.3))

    # Flatten the cheek sides slightly (narrow face) and the back of skull
    if Y < 0:
        fx = gauss(X, Z, 0.0, 0.1, 0.9, 1.4)
        X *= 1.0 - 0.0 * fx
    return Vector((X, Y, Z))


def head_features(v):
    """Add facial relief (nose, lips, cheeks, brow) to a base head point."""
    X, Y, Z = v
    if Y > 0.2:
        return v
    front = smoothstep(0.2, -0.5, Y)
    ax = abs(X)
    d = 0.0  # forward (-y) displacement

    # forehead fullness & brow softness
    d += 0.02 * gauss(X, Z, 0.0, 0.45, 0.45, 0.35)
    d += 0.015 * gauss(ax, Z, 0.30, 0.15, 0.16, 0.06)

    # Nose bridge (high, straight, slim) -> small upturned tip
    bridge_h = smoothstep(0.10, -0.06, Z) * (0.045 + 0.11 * smoothstep(-0.02, -0.36, Z))
    bridge_w = 0.055 + 0.03 * smoothstep(-0.1, -0.38, Z)
    nose = bridge_h * math.exp(-(X / bridge_w) ** 2)
    nose *= smoothstep(-0.47, -0.385, Z)
    tip = 0.06 * gauss(X, Z, 0.0, -0.36, 0.065, 0.055)
    alae = 0.032 * (gauss(X, Z, 0.085, -0.415, 0.05, 0.04) +
                    gauss(X, Z, -0.085, -0.415, 0.05, 0.04))
    under = -0.02 * gauss(X, Z, 0.0, -0.455, 0.07, 0.025)
    d += nose + tip + alae + under
    # sides of the nose sink a little into the eye/cheek valley
    d -= 0.02 * gauss(ax, Z, 0.14, -0.2, 0.04, 0.12)

    # Philtrum dip
    d -= 0.012 * gauss(X, Z, 0.0, -0.515, 0.03, 0.035)
    d += 0.006 * (gauss(X, Z, 0.03, -0.52, 0.012, 0.04) +
                  gauss(X, Z, -0.03, -0.52, 0.012, 0.04))

    # Lips
    zl, zm, zu = lip_bounds(X)
    if zu > zm:
        vu = (Z - zm) / (zu - zm)
        if -0.3 < vu < 1.3:
            prof = math.sin(math.pi * clamp(vu * 0.9 + 0.05)) ** 0.6
            d += 0.048 * prof * smoothstep(1.25, 0.95, vu) * smoothstep(0.205, 0.12, ax)
    if zm > zl:
        vl = (zm - Z) / (zm - zl)
        if -0.3 < vl < 1.3:
            prof = math.sin(math.pi * clamp(vl * 0.85 + 0.12)) ** 0.5
            d += 0.062 * prof * smoothstep(1.25, 0.95, vl) * smoothstep(0.185, 0.10, ax)
    # mouth line
    d -= 0.03 * math.exp(-((Z - zm) / 0.008) ** 2) * smoothstep(0.19, 0.13, ax)
    # mouth corners dimple
    d -= 0.012 * gauss(ax, Z, 0.19, MOUTH_Z + 0.01, 0.025, 0.03)
    # chin pad
    d += 0.035 * gauss(X, Z, 0.0, -0.83, 0.11, 0.08)
    d -= 0.012 * gauss(X, Z, 0.0, -0.73, 0.12, 0.035)

    # Apple cheeks
    cheek = 0.045 * gauss(ax, Z, 0.40, -0.30, 0.17, 0.15)
    # Aegyo-sal (卧蚕) under the eyes
    u = (ax - EYE_CX) / EYE_A
    aeg_z = eye_center_z(u) - eye_lower(u) - 0.032
    aegyo = 0.018 * math.exp(-((Z - aeg_z) / 0.022) ** 2) * smoothstep(1.05, 0.6, abs(u))

    radial = Vector((X, Y * 0.2, 0.0))
    if radial.length > 1e-6:
        radial.normalize()
    out = Vector((X, Y - d * front, Z))
    out += radial * cheek * front
    out.y -= aegyo * front
    return out


def brow_center(s):
    """Soft, nearly straight brow (平眉): s = 0 inner end -> 1 tail."""
    x = lerp(0.12, 0.60, s)
    z = 0.165 + 0.035 * math.sin(math.pi * min(1, s / 0.7) * 0.5) - 0.05 * smoothstep(0.7, 1.0, s)
    return x, z


def brow_half(s):
    return lerp(0.034, 0.010, smoothstep(0.3, 1.0, s))


BROW_PAINT = srgb("#8A6655")


def paint_head(X, Y, Z):
    """Make-up colour + gloss mask for a head vertex."""
    col = SKIN
    gloss = 0.0
    if Y > 0.3:
        return col, gloss
    ax = abs(X)
    # soft shading of jaw/temples
    col = mix3(col, SKIN_SHADOW, 0.35 * smoothstep(0.45, 0.66, ax) * smoothstep(0.0, -0.6, Z))
    # blush: cheeks + nose tip (晒伤妆)
    b = 0.75 * gauss(ax, Z, 0.40, -0.30, 0.17, 0.11)
    b += 0.35 * gauss(X, Z, 0.0, -0.36, 0.06, 0.05)
    b += 0.25 * gauss(ax, Z, 0.27, -0.24, 0.30, 0.06)
    col = mix3(col, BLUSH, clamp(b) * 0.65)
    # nose-bridge / forehead / chin highlight
    h = 0.45 * math.exp(-(X / 0.035) ** 2) * smoothstep(-0.08, -0.2, Z) * smoothstep(-0.36, -0.26, Z)
    h += 0.4 * gauss(X, Z, 0.0, 0.42, 0.12, 0.12)
    h += 0.4 * gauss(X, Z, 0.0, -0.83, 0.06, 0.04)
    # eye shadow above upper lid, stronger at outer corner
    u = (ax - EYE_CX) / EYE_A
    if -1.4 < u < 1.6:
        top = eye_center_z(u) + eye_upper(u)
        dz = Z - top
        s = math.exp(-(dz / 0.075) ** 2) * (0.5 + 0.5 * smoothstep(-0.6, 1.0, u)) if dz > -0.01 else 0
        s *= smoothstep(1.6, 1.0, u) * smoothstep(-1.4, -0.9, u)
        col = mix3(col, SHADOW_EYE, clamp(s) * 0.7)
        # aegyo-sal highlight with a soft shadow beneath it
        low = eye_center_z(u) - eye_lower(u)
        dz2 = low - Z
        hs = math.exp(-((dz2 - 0.03) / 0.018) ** 2) * smoothstep(1.1, 0.5, abs(u))
        sh = math.exp(-((dz2 - 0.06) / 0.012) ** 2) * smoothstep(1.0, 0.5, abs(u))
        col = mix3(col, SHADOW_EYE, clamp(sh) * 0.35)
        h += hs * 0.9
        # outer-corner pink under lower lash line
        col = mix3(col, BLUSH, 0.4 * gauss(u, dz2, 0.8, 0.02, 0.4, 0.04))
    col = mix3(col, HIGHLIGHT, clamp(h) * 0.55)
    # soft powder underlay for the brows
    if 0.08 < ax < 0.66 and 0.05 < Z < 0.28:
        sb = clamp((ax - 0.12) / 0.48)
        bx, bz = brow_center(sb)
        w = brow_half(sb) * 1.1
        b = math.exp(-((Z - bz) / w) ** 4) * smoothstep(0.08, 0.15, ax) * smoothstep(0.66, 0.58, ax)
        col = mix3(col, BROW_PAINT, clamp(b) * lerp(0.35, 0.75, smoothstep(0.0, 0.4, sb)))
    # lips: gradient bitten lip
    zl, zm, zu = lip_bounds(X)
    if zl - 0.03 < Z < zu + 0.03 and ax < 0.22:
        inside_u = smoothstep(zu + 0.008, zu - 0.008, Z)
        inside_l = smoothstep(zl - 0.008, zl + 0.008, Z)
        edge_x = smoothstep(0.205 if Z > zm else 0.185, 0.16, ax)
        m = inside_u * inside_l * edge_x
        core = math.exp(-((X / 0.10) ** 2 + ((Z - zm) / 0.045) ** 2))
        lip = mix3(LIP_OUT, LIP_IN, clamp(core * 1.2))
        col = mix3(col, lip, m)
        gloss = m * (0.6 + 0.4 * gauss(X, Z, 0.0, zm - 0.04, 0.08, 0.03))
    return col, gloss


def build_head(root):
    cuts = 70 if QUICK else 100
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    for v in bm.verts:
        v.co = head_features(head_base(v.co.normalized()))
    obj = mesh_object("Head", bm, root)

    # Find the eye surface depth before carving the sockets
    tree = bvh_of([obj])
    eye_front = {}
    for side in (1, -1):
        hit = tree.ray_cast(Vector((side * EYE_CX, -5.0, EYE_CZ)), Vector((0, 1, 0)))
        eye_front[side] = hit[0].y

    me = obj.data
    for v in me.vertices:
        X, Y, Z = v.co
        if Y < 0:
            e = eye_metric(X, Z)
            if e < 1.6:
                v.co.y += EYE_DEPTH * smoothstep(1.35, 0.55, e)
                # upper lid fold rolls outward a bit at the lash line
                u = (abs(X) - EYE_CX) / EYE_A
                if Z > eye_center_z(u):
                    v.co.y -= 0.012 * math.exp(-((e - 1.15) / 0.18) ** 2)

    # Paint
    attr = me.color_attributes.new("paint", "FLOAT_COLOR", "POINT")
    gl = me.attributes.new("gloss", "FLOAT", "POINT")
    for i, v in enumerate(me.vertices):
        c, g = paint_head(*v.co)
        attr.data[i].color = (*c, 1.0)
        gl.data[i].value = g
    shade_smooth(obj)
    add_subsurf(obj, 1, 2)
    obj.data.materials.append(mat_skin("FaceSkin", with_paint=True))
    return obj, eye_front


# ---------------------------------------------------------------------------
# Eyes, lashes, brows
# ---------------------------------------------------------------------------

def build_eyes(root, head, eye_front):
    m_sclera = mat_simple("Sclera", srgb("#F4EEEC"), 0.15, Coat_Weight=1.0,
                          Subsurface_Weight=0.1)
    m_iris = mat_iris()
    m_catch = mat_emit("Catchlight", (1, 1, 1), 8.0)
    eyes = []
    for side in (1, -1):
        cx = side * EYE_CX
        yf = eye_front[side]
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=32, radius=1.0)
        rx, ry, rz = 0.215, 0.16, 0.16
        bmesh.ops.scale(bm, vec=(rx, ry, rz), verts=bm.verts)
        eye = mesh_object("Eye.%s" % ("L" if side > 0 else "R"), bm, root)
        eye.location = (cx, yf + 0.035 + ry, EYE_CZ + 0.005)
        eye.rotation_euler = (0, 0, -side * math.radians(14))
        shade_smooth(eye)
        eye.data.materials.append(m_sclera)

        # Iris disc (big coloured contacts)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=1.0)
        iris = mesh_object("Iris.%s" % ("L" if side > 0 else "R"), bm, root)
        r_iris = 0.098
        iris.scale = (r_iris, 0.022, r_iris)
        iris.location = (cx - side * 0.006, yf + 0.035 - 0.003, EYE_CZ - 0.004)
        iris.rotation_euler = (0, 0, -side * math.radians(5))
        shade_smooth(iris)
        iris.data.materials.append(m_iris)
        # Catch lights
        for off, r in (((-0.035, -0.03, 0.035), 0.019), ((0.03, -0.03, -0.035), 0.008)):
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r)
            c = mesh_object("Catch", bm, root)
            c.location = Vector(iris.location) + Vector((off[0], off[1] + 0.012, off[2]))
            c.data.materials.append(m_catch)
            c.visible_shadow = False
        eyes.append(eye)
    return eyes


def lid_points(tree, side, upper=True, n=40, u0=-1.0, u1=1.0, lift=0.0, out=0.006):
    """Points along the lid edge projected onto the face (head-local)."""
    pts = []
    for i in range(n):
        u = lerp(u0, u1, i / (n - 1))
        uc = clamp(u, -1, 1)
        zc = eye_center_z(u)
        z = zc + (eye_upper(uc) * 0.96 + lift if upper else -eye_lower(uc) * 0.92 - lift)
        if u > 1.0:  # winged liner continues up & out
            z = eye_center_z(1.0) + (u - 1.0) * 0.45 + lift
        x = side * (EYE_CX + u * EYE_A)
        hit = tree.ray_cast(Vector((x, -5.0, z)), Vector((0, 1, 0)))
        if hit[0] is None:
            continue
        p = hit[0] + hit[1] * out
        pts.append(p)
    return pts


def build_lashes_brows(root, head, eyes):
    tree = bvh_of([head] + eyes)
    head_tree = bvh_of([head])
    m_lash = mat_simple("Lash", srgb("#120C0A"), 0.4)
    m_brow = mat_hair("Brow", melanin=0.75, redness=0.45, rough=0.45)
    m_crease = mat_simple("Crease", srgb("#B5786A"), 0.6)
    liner, lashes, crease, brows = [], [], [], []
    for side in (1, -1):
        # eyeliner with a small wing
        pts = lid_points(tree, side, True, 44, -0.98, 1.22, out=0.004)
        radii = []
        for i in range(len(pts)):
            t = i / (len(pts) - 1)
            radii.append(0.25 + 0.95 * math.sin(math.pi * min(1, t * 1.15)) ** 0.7 if t < 0.82
                         else max(0.05, 1.0 - (t - 0.82) / 0.18))
        liner.append((pts, radii))
        # lower lash line (thin brown)
        pts = lid_points(tree, side, False, 30, -0.75, 1.0, out=0.003)
        lashes.append((pts, [0.25 + 0.2 * (i / 29) for i in range(len(pts))]))

        # double-eyelid crease
        cp = lid_points(head_tree, side, True, 30, -0.75, 1.08, lift=0.038, out=0.002)
        crease.append((cp, [0.25 + 0.6 * math.sin(math.pi * i / 29) for i in range(len(cp))]))

        # upper lashes, grouped into manga-style clusters
        base = lid_points(tree, side, True, 60, -0.85, 1.08, out=0.004)
        for i, b in enumerate(base):
            t = i / (len(base) - 1)
            length = lerp(0.07, 0.15, smoothstep(0.0, 0.85, t))
            cluster = (i // 4) * 4 + 2
            ct = cluster / (len(base) - 1)
            ang_out = lerp(-0.2, 0.9, ct)
            tipdir = Vector((side * ang_out, -0.9, 1.2)).normalized()
            p0 = b
            p1 = b + Vector((side * ang_out * 0.25, -0.05, 0.015)) * (length / 0.12)
            p2 = b + tipdir * length * 0.75 + Vector((0, 0.01, 0.0))
            p3 = b + tipdir * length + Vector((0, 0.035, 0.03)) * (length / 0.12)
            lashes.append(([p0, p1, p2, p3], [1.0, 0.8, 0.45, 0.05]))
        # lower spiky lash clusters
        base = lid_points(tree, side, False, 6, -0.35, 0.75, out=0.003)
        for b in base:
            for k in range(2):
                tip = b + Vector((side * (0.006 * k + 0.008), -0.03, -0.035 - 0.006 * k))
                lashes.append(([b, b.lerp(tip, 0.5), tip], [0.6, 0.4, 0.05]))

        # eyebrows: many short hairs inside a soft straight-ish brow shape
        for _ in range(420 if not QUICK else 200):
            s = random.random() ** 1.1
            bx, bz = brow_center(s)
            hw = brow_half(s)
            off = random.uniform(-1, 1) * hw
            x0, z0 = bx, bz + off
            if s < 0.2:
                d2 = Vector((0.25, 1.0))
            else:
                d2 = Vector((1.0, 0.25 - 0.6 * smoothstep(0.6, 1.0, s) - off / hw * 0.25))
            d2.normalize()
            ln = random.uniform(0.04, 0.07)
            pts = []
            for k in range(3):
                q = Vector((x0, z0)) + d2 * ln * k / 2
                hit = head_tree.ray_cast(Vector((side * q.x, -5, q.y)), Vector((0, 1, 0)))
                if hit[0] is None:
                    break
                pts.append(hit[0] + hit[1] * (0.004 + 0.004 * k))
            if len(pts) == 3:
                brows.append((pts, [1.0, 0.7, 0.2]))

    curve_object("Eyeliner", liner, 0.010, root, mat=m_lash)
    curve_object("Lashes", lashes, 0.0045, root, mat=m_lash)
    curve_object("Crease", crease, 0.004, root, mat=m_crease)
    curve_object("Brows", brows, 0.0045, root, mat=m_brow, bevel_res=1)


# ---------------------------------------------------------------------------
# Body (metaballs -> mesh)
# ---------------------------------------------------------------------------

MB_K = 1.0 / 0.574  # metaball radius -> surface radius


def mb_ball(mb, co, r, stiff=2.0):
    e = mb.elements.new(type="BALL")
    e.co = co
    e.radius = r * MB_K
    e.stiffness = stiff
    return e


def mb_ellip(mb, co, axes, rot=None, stiff=2.0):
    e = mb.elements.new(type="ELLIPSOID")
    r = max(axes)
    e.co = co
    e.radius = r * MB_K
    e.size_x, e.size_y, e.size_z = (a / r for a in axes)
    if rot is not None:
        e.rotation = rot
    e.stiffness = stiff
    return e


def mb_capsule(mb, a, b, r, stiff=2.0):
    a, b = Vector(a), Vector(b)
    d = b - a
    e = mb.elements.new(type="CAPSULE")
    e.co = (a + b) / 2
    e.radius = r * MB_K
    e.size_x = d.length / 2
    e.rotation = Vector((1, 0, 0)).rotation_difference(d.normalized())
    e.stiffness = stiff
    return e


def mb_chain(mb, pts, radii, steps=4, stiff=2.0):
    """Smooth tapering limb from a polyline with per-point radii."""
    for i in range(len(pts) - 1):
        a, b = Vector(pts[i]), Vector(pts[i + 1])
        for k in range(steps):
            t0, t1 = k / steps, (k + 1) / steps
            r = lerp(radii[i], radii[i + 1], (t0 + t1) / 2)
            mb_capsule(mb, a.lerp(b, t0), a.lerp(b, t1), r, stiff)


def metaball_to_mesh(name, build, res):
    mb = bpy.data.metaballs.new(name + "_mb")
    mb.resolution = res
    mb.render_resolution = res
    mb.threshold = 0.6
    tmp = bpy.data.objects.new(name + "_mb", mb)
    link(tmp)
    build(mb)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = tmp.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    bpy.data.objects.remove(tmp)
    bpy.data.metaballs.remove(mb)
    me.name = name
    obj = bpy.data.objects.new(name, me)
    link(obj)
    # tidy the marching-cubes surface
    sm = obj.modifiers.new("Smooth", "CORRECTIVE_SMOOTH")
    sm.iterations = 6
    sm.use_only_smooth = True
    shade_smooth(obj)
    return obj


def build_body():
    res = 0.009 if QUICK else 0.006

    def torso(mb):
        # neck (slender swan neck), shoulders, chest, waist, hips
        mb_chain(mb, [(0, 0.012, 1.36), (0, 0.006, 1.45), (0, 0.004, 1.53)],
                 [0.040, 0.035, 0.034], steps=4)
        mb_ellip(mb, (0, 0.012, 1.31), (0.13, 0.07, 0.055))
        for s in (1, -1):
            mb_capsule(mb, (s * 0.03, 0.014, 1.40), (s * 0.135, 0.012, 1.345), 0.036)
            mb_ball(mb, (s * 0.148, 0.012, 1.325), 0.043)
            mb_ellip(mb, (s * 0.075, 0.025, 1.24), (0.065, 0.065, 0.07))  # lats
        mb_ellip(mb, (0, 0.012, 1.19), (0.12, 0.082, 0.12))      # rib cage
        mb_ellip(mb, (0, 0.010, 1.04), (0.096, 0.072, 0.09))     # slim waist
        mb_ellip(mb, (0, 0.012, 0.92), (0.125, 0.088, 0.075))    # pelvis
        mb_ellip(mb, (0, -0.02, 0.97), (0.085, 0.06, 0.07))      # belly
        for s in (1, -1):
            mb_ellip(mb, (s * 0.08, 0.01, 0.87), (0.068, 0.078, 0.08))      # hips
            mb_ellip(mb, (s * 0.06, 0.055, 0.86), (0.07, 0.06, 0.075))      # glutes
            mb_ellip(mb, (s * 0.058, -0.06, 1.20), (0.058, 0.05, 0.052))    # bust
            # long slim legs in heels (feet en pointe)
            mb_chain(mb, [(s * 0.082, 0.010, 0.85), (s * 0.078, 0.004, 0.66),
                          (s * 0.070, 0.0, 0.47), (s * 0.066, 0.012, 0.36),
                          (s * 0.062, 0.010, 0.22), (s * 0.058, 0.010, 0.11)],
                     [0.068, 0.056, 0.042, 0.042, 0.029, 0.022], steps=5)
            mb_ellip(mb, (s * 0.066, 0.022, 0.33), (0.036, 0.034, 0.07))    # calf
            mb_chain(mb, [(s * 0.058, 0.012, 0.105), (s * 0.060, -0.03, 0.06),
                          (s * 0.062, -0.085, 0.014), (s * 0.063, -0.11, 0.010)],
                     [0.028, 0.024, 0.021, 0.016], steps=3)

    body = metaball_to_mesh("Body", torso, res)
    body.data.materials.append(mat_body())

    arm_mat = mat_skin("ArmSkin")
    arms = []
    for s in (1, -1):
        def arm(mb, s=s):
            sh = Vector((s * 0.155, 0.012, 1.325))
            if s > 0:
                # hand on hip (叉腰): elbow out, wrist resting at the waist
                el = Vector((0.285, 0.05, 1.12))
                wr = Vector((0.145, 0.03, 0.985))
                fwd = Vector((-0.4, -0.05, -1.0)).normalized()
            else:
                el = Vector((-0.215, 0.03, 1.09))
                wr = Vector((-0.24, -0.005, 0.855))
                fwd = Vector((-0.1, -0.05, -1.0)).normalized()
            mid1 = sh.lerp(el, 0.5) + Vector((s * 0.008, 0.0, 0.0))
            mb_chain(mb, [sh, mid1, el], [0.037, 0.032, 0.026], 5)
            mb_chain(mb, [el, el.lerp(wr, 0.45), wr], [0.026, 0.026, 0.020], 5)
            # hand: palm + gently curled fingers
            palm = wr + fwd * 0.045
            mb_ellip(mb, palm, (0.040, 0.012, 0.035),
                     rot=Vector((0, 0, 1)).rotation_difference(fwd)
                     @ Quaternion((0, 0, 1), math.radians(90)))
            side_v = fwd.cross(Vector((0, 1, 0))).normalized()
            for fo, fl in ((-0.026, 0.060), (-0.009, 0.068), (0.008, 0.064), (0.024, 0.052)):
                a = palm + fwd * 0.03 + side_v * fo
                b = a + fwd * fl * 0.5 + Vector((0, -0.006, 0))
                c = b + fwd * fl * 0.35 + Vector((0, 0.01, 0))
                mb_chain(mb, [a, b, c], [0.0085, 0.0075, 0.0062], 3)
            ta = palm - side_v * 0.03 + Vector((0, -0.01, 0))
            tb = ta + fwd * 0.03 + Vector((0, -0.015, 0))
            mb_chain(mb, [ta, tb, tb + fwd * 0.022], [0.011, 0.0085, 0.007], 3)
        o = metaball_to_mesh("Arm.%s" % ("L" if s > 0 else "R"), arm, res * 0.8)
        o.data.materials.append(arm_mat)
        arms.append(o)

    # heels: stiletto + sole
    heel_mat = mat_simple("Heel", srgb("#E2BBA6"), 0.15, Coat_Weight=0.8)
    for s in (1, -1):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.006,
                              radius2=0.011, depth=0.085)
        h = mesh_object("Stiletto", bm)
        h.location = (s * 0.058, 0.03, 0.0425)
        h.data.materials.append(heel_mat)
        shade_smooth(h)
        # thin ankle strap
        bm = bmesh.new()
        bmesh.ops.create_circle(bm, cap_ends=False, segments=24, radius=0.031)
        st = mesh_object("Strap", bm)
        st.location = (s * 0.058, 0.008, 0.10)
        st.rotation_euler = (math.radians(-12), 0, 0)
        st.modifiers.new("Skin", "SKIN")
        for v in st.data.skin_vertices[0].data:
            v.radius = (0.003, 0.003)
        st.data.materials.append(heel_mat)
    return body, arms


def build_dress(body):
    """Bias-cut slip dress: a body-fitted satin skirt that flares from the hip."""
    m = mat_dress()
    tree = bvh_of([body], world=True)
    bm = bmesh.new()
    rings = 30
    seg = 72
    z_top, z_hip = 1.06, 0.88
    rows = []
    prev = [0.0] * seg
    for i in range(rings):
        t = i / (rings - 1)
        z = lerp(z_top, DRESS_HEM - 0.005, t)
        below_hip = z < z_hip
        flare = 0.045 * smoothstep(z_hip, DRESS_HEM, z) if below_hip else 0.0
        row = []
        for j in range(seg):
            a = 2 * math.pi * j / seg
            dirv = Vector((math.sin(a), -math.cos(a), 0))
            o = Vector((0, 0.012, z))
            hit = tree.ray_cast(o + dirv * 0.4, -dirv)
            r = (hit[0] - o).length if hit[0] is not None else prev[j]
            r += 0.004
            if below_hip:
                r = max(r, prev[j])
            prev[j] = r
            fold = 1.0 + (0.035 * math.sin(7 * a + 0.6) + 0.015 * math.sin(13 * a)) \
                * smoothstep(z_hip, DRESS_HEM, z)
            row.append(bm.verts.new(o + dirv * (r + flare) * fold))
        rows.append(row)
    for i in range(rings - 1):
        for j in range(seg):
            bm.faces.new((rows[i][j], rows[i][(j + 1) % seg],
                          rows[i + 1][(j + 1) % seg], rows[i + 1][j]))
    skirt = mesh_object("Skirt", bm)
    sol = skirt.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.003
    add_subsurf(skirt, 1, 2)
    shade_smooth(skirt)
    skirt.data.materials.append(m)

    # Push the skirt outside the body where needed
    me = skirt.data
    for v in me.vertices:
        loc, nrm, idx, dist = tree.find_nearest(v.co)
        if loc is None:
            continue
        outward = (v.co - loc)
        inside = outward.dot(nrm) < 0
        if inside or dist < 0.006:
            v.co = loc + nrm * 0.008

    # straps
    straps = []
    for s in (1, -1):
        pts = [Vector((s * 0.068, -0.075, DRESS_TOP - 0.01)),
               Vector((s * 0.085, -0.06, 1.30)),
               Vector((s * 0.105, -0.02, 1.37)),
               Vector((s * 0.11, 0.04, 1.36)),
               Vector((s * 0.095, 0.08, 1.27)),
               Vector((s * 0.08, 0.085, DRESS_TOP - 0.02))]
        fixed = []
        for p in pts:
            loc, nrm, idx, dist = tree.find_nearest(p)
            fixed.append(loc + nrm * 0.003)
        straps.append((fixed, [1.0] * len(fixed)))
    curve_object("Straps", straps, 0.0022, mat=m)
    return skirt


# ---------------------------------------------------------------------------
# Hair
# ---------------------------------------------------------------------------

def hair_curves_object(name, strands, mat, parent=None):
    """Native hair-curves object (rendered as thin Cycles curves)."""
    hc = bpy.data.hair_curves.new(name)
    hc.add_curves([len(p) for p, _ in strands])
    flat, rads = [], []
    for pts, rr in strands:
        for p, r in zip(pts, rr):
            flat.extend((p[0], p[1], p[2]))
            rads.append(r)
    hc.position_data.foreach_set("vector", flat)
    rad = hc.attributes.new("radius", "FLOAT", "POINT")
    rad.data.foreach_set("value", rads)
    hc.materials.append(mat)
    obj = bpy.data.objects.new(name, hc)
    link(obj, parent)
    return obj


def build_hair(root, head, body, arms):
    m_hair = mat_hair("Hair", melanin=0.82, redness=0.55, rough=0.28)
    m_cap = mat_simple("HairCap", srgb("#24140E"), 0.95, Specular_IOR_Level=0.1)

    head_tree = bvh_of([head])
    body_tree = bvh_of([body] + arms, world=True)
    M = root.matrix_world
    head_c = M @ Vector((0, 0.05, 0.1))

    # --- scalp cap (hides skin under strands)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=128, v_segments=80, radius=1.0)
    drop = [v for v in bm.verts if not hairline_ok(v.co.normalized())]
    bmesh.ops.delete(bm, geom=drop, context="VERTS")
    for v in bm.verts:
        d = v.co.normalized()
        hit = head_tree.ray_cast(d * 3.0, -d)
        if hit[0] is not None:
            v.co = hit[0] + d * 0.035
    cap = mesh_object("HairCap", bm, root)
    shade_smooth(cap)
    cap.data.materials.append(m_cap)

    def scalp_point(d, lift):
        hit = head_tree.ray_cast(d * 3.0, -d)
        if hit[0] is None:
            return None
        return hit[0] + d * lift

    def fall(wpts, side, layer, in_front, end_z, margin0=0.010):
        """Let a strand hang under gravity, draping over body & shoulders."""
        cur = wpts[-1].copy()
        vel = (wpts[-1] - wpts[-2]).normalized() if len(wpts) > 1 else Vector((0, 0, -1))
        vel += Vector((side * random.uniform(0.0, 0.25), 0.0, 0.0))
        while cur.z > end_z:
            vel = (vel + Vector((0, 0, -0.35))).normalized()
            nxt = cur + vel * 0.012
            margin = margin0 + 0.010 * layer
            loc, nrm, idx, dist = body_tree.find_nearest(nxt)
            if loc is not None:
                if (nxt - loc).dot(nrm) < 0 or dist < margin:
                    nxt = loc + nrm * margin
                elif nxt.z < 1.32 and dist > margin * 1.5:
                    # hair settles onto the back / chest instead of floating
                    target = loc + nrm * margin
                    pull = Vector((target.x - nxt.x, target.y - nxt.y, 0))
                    nxt += pull * (0.06 if not in_front else 0.04)
            if not in_front and nxt.z < 1.45 and nxt.y < 0.03 and abs(nxt.x) > 0.07:
                nxt.y = max(nxt.y, lerp(0.03, 0.07, smoothstep(1.45, 1.30, nxt.z)))
            wpts.append(nxt)
            cur = nxt
        return wpts

    guides = []
    n_main = 900 if QUICK else 1800
    for i in range(n_main):
        while True:
            d = Vector((random.gauss(0, 1), random.gauss(0, 1), random.gauss(0, 1))).normalized()
            if hairline_ok(d) and d.z > -0.15:
                break
        side = 1 if d.x >= 0 else -1
        if abs(d.x) < 0.02:
            d.x = side * 0.02
            d.normalize()
        layer = random.random()
        lift = 0.05 + 0.12 * layer * (0.6 + 0.4 * max(0.0, d.z))
        p = scalp_point(d, lift)
        if p is None:
            continue
        pts = [p]
        # comb from the centre part outward & down over the skull
        dirv = d.copy()
        front = smoothstep(-0.2, -0.85, d.y)
        thr_side = lerp(-0.05, 0.05, front) + random.uniform(-0.2, 0.1)
        thr_back = random.uniform(-0.55, -0.25)
        for step in range(60):
            g = Vector((0, 0, -1.0))
            away = Vector((side, 0.0, 0.0)) * (0.6 + 2.2 * front)
            back = Vector((0, 0.35 * (1 - front), 0))
            t = g + away + back
            t -= dirv * t.dot(dirv)
            if t.length < 1e-4:
                break
            t.normalize()
            dirv = (dirv + t * 0.05).normalized()
            q = scalp_point(dirv, lift + 0.03 * step / 60 + 0.02 * front)
            if q is None:
                break
            pts.append(q)
            if dirv.z < thr_side and abs(dirv.x) > 0.55:
                break
            if dirv.z < thr_back:
                break
        wpts = [M @ q for q in pts]
        in_front = (pts[-1]).y < -0.15
        end_z = random.uniform(1.00, 1.08) if in_front else random.uniform(1.0, 1.10)
        wpts = fall(wpts, side, layer, in_front, end_z)
        # soft C-curl at the ends
        for k in range(1, min(5, len(wpts))):
            wpts[-k] = wpts[-k] + Vector((-side * 0.003 * (5 - k), 0.004 * (5 - k), 0))
        guides.append((resample(wpts, 0.012), side, layer))

    # --- curtain bangs (八字刘海), framing the face
    for i in range(160 if QUICK else 320):
        sgn = 1 if i % 2 else -1
        s = random.random()
        d = Vector((sgn * lerp(0.03, 0.30, s), -0.75, 0.62 + 0.08 * (1 - s))).normalized()
        p = scalp_point(d, 0.05)
        if p is None:
            continue
        pts = [p]
        n = 22
        for k in range(1, n):
            t = k / (n - 1)
            target_x = sgn * lerp(abs(p.x), 0.62 + 0.15 * s, t ** 1.2)
            target_z = lerp(p.z, lerp(0.05, -0.55, s) + random.uniform(-0.05, 0.05), t ** 0.9)
            hit = head_tree.ray_cast(Vector((target_x, -3.0, target_z)), Vector((0, 1, 0)))
            if hit[0] is None:
                q = pts[-1] + Vector((sgn * 0.01, 0.02, -0.05))
            else:
                q = hit[0] + Vector((0, -lerp(0.06, 0.04 + 0.02 * s, t), 0))
            pts.append(q)
        wpts = [M @ q for q in pts]
        wpts = fall(wpts, sgn, 0.3, True, random.uniform(1.12, 1.30))
        guides.append((resample(wpts, 0.010), sgn, 0.3))

    # --- children: interpolate several thin strands around each guide
    strands = []
    kids = 5 if QUICK else 9
    for pts, side, layer in guides:
        n = len(pts)
        for c in range(kids):
            o = Vector((random.gauss(0, 1), random.gauss(0, 1), random.gauss(0, 1)))
            o = o.normalized() * random.uniform(0.0, 0.006)
            cut = random.uniform(0.85, 1.0) if c else 1.0
            m = max(3, int(n * cut))
            ph = random.uniform(0, 6.28)
            cp = []
            for k in range(m):
                t = k / max(1, n - 1)
                p = pts[k]
                off = o * lerp(1.0, 0.35, t ** 1.5)
                if (p - head_c).length < 0.13:
                    # stay tangent to the scalp
                    nrm = (p - head_c).normalized()
                    off = off - nrm * min(0.0, off.dot(nrm)) * 0 - nrm * off.dot(nrm)
                off += Vector((math.sin(ph + t * 9), math.cos(ph + t * 7), 0)) * 0.0012 * t
                cp.append(p + off)
            rr = [lerp(0.00032, 0.00008, (k / max(1, m - 1)) ** 2) for k in range(m)]
            strands.append((cp, rr))
    hair = hair_curves_object("Hair", strands, m_hair)
    bpy.context.scene.cycles_curves.shape = "THICK"
    return hair


def hairline_ok(d):
    """Is this scalp direction (head-local unit vector) inside the hairline?"""
    x, y, z = d
    if z > 0.45:
        return True
    # forehead hairline
    if y < -0.3:
        return z > 0.48 - 0.15 * abs(x)
    # temples / sideburns in front of the ear
    if y < 0.15:
        return z > 0.05 - 0.4 * (y + 0.3) * 0.0 and z > -0.05 + 0.35 * max(0, -y)
    # back: down to the nape
    return z > -0.55


def resample(pts, step):
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = (b - a).length
        if seg < 1e-9:
            continue
        pos = 0.0
        while acc + (seg - pos) >= step:
            pos += step - acc
            out.append(a.lerp(b, pos / seg))
            acc = 0.0
        acc += seg - pos
    if (out[-1] - pts[-1]).length > step * 0.3:
        out.append(pts[-1])
    return out


# ---------------------------------------------------------------------------
# Earrings (small pearl drops)
# ---------------------------------------------------------------------------

def build_accessories(root):
    pearl = mat_simple("Pearl", srgb("#F7EFE8"), 0.12, Coat_Weight=1.0,
                       Sheen_Weight=0.5)
    gold = mat_simple("Gold", srgb("#E8C27A"), 0.2, Metallic=1.0)
    for s in (1, -1):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=14, radius=0.065)
        p = mesh_object("Pearl", bm, root)
        p.location = (s * 0.70, 0.08, -0.58)
        shade_smooth(p)
        p.data.materials.append(pearl)
    # delicate necklace
    pts = []
    for i in range(41):
        a = lerp(-1.25, 1.25, i / 40)
        pts.append(Vector((0.058 * math.sin(a) * 1.25, -0.048 * math.cos(a) + 0.006,
                           1.395 - 0.03 * math.cos(a))))
    curve_object("Necklace", [(pts, [1.0] * len(pts))], 0.0009, mat=gold)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=0.0045)
    pend = mesh_object("Pendant", bm)
    pend.location = (0, -0.046, 1.357)
    pend.data.materials.append(pearl)


# ---------------------------------------------------------------------------
# Studio: ring light, pastel backdrop, cameras
# ---------------------------------------------------------------------------

def build_studio():
    scn = bpy.context.scene
    # backdrop: seamless sweep
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=40, size=1.0)
    for v in bm.verts:
        t = (v.co.y + 1) / 2  # 0 front -> 1 back
        x = v.co.x * 4.0
        if t < 0.6:
            y = lerp(-3.0, 0.9, t / 0.6)
            z = 0.0
        else:
            a = (t - 0.6) / 0.4 * math.pi / 2
            y = 0.9 + 0.8 * math.sin(a)
            z = 0.8 * (1 - math.cos(a))
        v.co = (x, y, z)
    back = mesh_object("Backdrop", bm)
    sol = back.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.01
    # wall behind the sweep
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)
    wall = mesh_object("Wall", bm)
    wall.scale = (4.0, 2.0, 1.0)
    wall.rotation_euler = (math.radians(90), 0, 0)
    wall.location = (0, 1.7, 2.8)

    mat, nodes, links = new_material("Backdrop")
    bsdf = principled(nodes)
    bsdf.inputs["Roughness"].default_value = 0.9
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*srgb("#F6D6DF"), 1)
    ramp.color_ramp.elements[1].color = (*srgb("#E6D9F5"), 1)
    links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    back.data.materials.append(mat)
    wall.data.materials.append(mat_simple("Wall", srgb("#E6D9F5"), 0.9))

    # world: soft neutral fill
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    scn.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (*srgb("#FBEFF3"), 1)
    bg.inputs["Strength"].default_value = 0.35

    def area(name, loc, target, size, power, color=(1, 1, 1), shape="DISK"):
        ld = bpy.data.lights.new(name, "AREA")
        ld.shape = shape
        ld.size = size
        ld.energy = power
        ld.color = color
        lo = bpy.data.objects.new(name, ld)
        link(lo)
        lo.location = loc
        d = Vector(target) - Vector(loc)
        lo.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return lo

    # Ring light right behind the camera (gives the round catch-light)
    area("RingLight", (0, -1.9, 1.62), (0, 0, 1.45), 0.75, 22, srgb("#FFF6F2"))
    area("SoftKey", (-1.5, -1.0, 2.1), (0, 0, 1.4), 1.0, 110, srgb("#FFF1EA"), "RECTANGLE")
    area("RimPink", (1.0, 0.9, 1.9), (0, 0, 1.35), 0.8, 45, srgb("#FFB3CB"))
    area("RimCool", (-1.0, 0.9, 1.8), (0, 0, 1.35), 0.8, 35, srgb("#C9D6FF"))
    area("Top", (0, 0.2, 2.6), (0, 0, 1.5), 0.8, 20, srgb("#FFFFFF"))


def add_camera(name, loc, target, lens, shift_y=0.0):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.shift_y = shift_y
    cd.dof.use_dof = True
    cd.dof.aperture_fstop = 2.8 if lens > 60 else 5.6
    co = bpy.data.objects.new(name, cd)
    link(co)
    co.location = loc
    d = Vector(target) - Vector(loc)
    co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cd.dof.focus_distance = d.length
    return co


def setup_render():
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = 48 if QUICK else 160
    scn.cycles.use_denoising = True
    scn.cycles.max_bounces = 8
    scn.cycles.transparent_max_bounces = 8
    scn.view_settings.view_transform = "AgX"
    try:
        scn.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    scn.view_settings.exposure = 0.0
    scn.render.film_transparent = False
    scn.render.image_settings.file_format = "PNG"


def render_shot(cam, path, res):
    scn = bpy.context.scene
    scn.camera = cam
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = 100
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("Rendered", path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    reset_scene()
    root = bpy.data.objects.new("HeadRoot", None)
    link(root)
    # a cute slight head tilt (歪头), pivoting where the head meets the neck
    tilt = Matrix.Rotation(math.radians(-6), 3, "Y")
    pivot = Vector((0.0, 0.0, 1.47))
    root.location = pivot + tilt @ (HEAD_POS - pivot)
    root.rotation_euler = tilt.to_euler()
    root.scale = (HU, HU, HU)
    bpy.context.view_layer.update()

    head, eye_front = build_head(root)
    eyes = build_eyes(root, head, eye_front)
    build_lashes_brows(root, head, eyes)
    body, arms = build_body()
    build_dress(body)
    bpy.context.view_layer.update()
    build_hair(root, head, body, arms)
    build_accessories(root)
    build_studio()
    setup_render()

    cam_full = add_camera("Cam_Full", (0.0, -2.95, 0.95), (0, 0, 0.88), 50)
    cam_portrait = add_camera("Cam_Portrait", (0.12, -1.25, 1.58), (0, 0, 1.50), 85)
    cam_side = add_camera("Cam_ThreeQuarter", (-0.75, -1.0, 1.60), (0, 0, 1.50), 85)
    cam_profile = add_camera("Cam_Profile", (-1.3, -0.02, 1.53), (0, -0.02, 1.53), 100)
    bpy.context.scene.camera = cam_full

    if not bpy.app.background:
        return  # run from Blender's Text Editor: just build the scene
    os.makedirs(OUT_DIR, exist_ok=True)
    blend = os.path.join(OUT_DIR, "douyin_girl.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("Saved", blend)

    if DO_RENDER:
        shots = {
            "portrait": (cam_portrait, (864, 1080) if not QUICK else (432, 540)),
            "full": (cam_full, (1080, 1920) if not QUICK else (360, 640)),
            "side": (cam_side, (864, 1080) if not QUICK else (432, 540)),
            "profile": (cam_profile, (864, 1080) if not QUICK else (432, 540)),
        }
        for key, (cam, res) in shots.items():
            if (ONLY and key not in ONLY) or (not ONLY and key == "profile"):
                continue
            render_shot(cam, os.path.join(OUT_DIR, "render_%s.png" % key), res)


if __name__ == "__main__":
    main()
