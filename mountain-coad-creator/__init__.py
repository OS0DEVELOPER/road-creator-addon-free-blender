bl_info = {
    "name": "Mountain Road Creator V6.3",
    "author": "OS0DEVELOPER",
    "version": (6, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Road Creator",
    "description": "True Multi-Bridge Spline Splitting (No Cross-Gap Wires/Pillars), Ground-Locked Asphalt/Offroad & Blue UI",
    "category": "Mesh",
    "doc_url": "https://github.com/OS0DEVELOPER/road-creator-addon-free-blender",
    "tracker_url": "https://github.com/OS0DEVELOPER/road-creator-addon-free-blender/issues",
    "license": "MIT",
}

import bpy
import bmesh
import math
from bpy.app.handlers import persistent
from mathutils import Vector
from mathutils.geometry import interpolate_bezier

# ==============================================================================
# HELPER: FAIL-SAFE SKY RAYCAST
# ==============================================================================
def create_sky_raycast(nodes, links, target_geo_socket, source_pos_socket=None):
    """Shoots a ray from +300m in the sky straight down so steep mountain cliffs never miss."""
    n_sky_add = nodes.new('ShaderNodeVectorMath')
    n_sky_add.operation = 'ADD'
    n_sky_add.inputs[1].default_value = (0.0, 0.0, 300.0)
    
    if source_pos_socket:
        links.new(source_pos_socket, n_sky_add.inputs[0])
    else:
        n_pos = nodes.new('GeometryNodeInputPosition')
        links.new(n_pos.outputs["Position"], n_sky_add.inputs[0])
        
    n_ray = nodes.new('GeometryNodeRaycast')
    n_ray.inputs["Ray Direction"].default_value = (0.0, 0.0, -1.0)
    n_ray.inputs["Ray Length"].default_value = 1000.0
    links.new(target_geo_socket, n_ray.inputs["Target Geometry"])
    links.new(n_sky_add.outputs["Vector"], n_ray.inputs["Source Position"])
    return n_ray


# ==============================================================================
# HELPER: SPLIT CURVE BY DELETING POINTS (STOPS BRIDGES/GUARDRAILS CONNECTING ACROSS GAPS!)
# ==============================================================================
def split_curve_by_deleting_points(nodes, links, curve_socket, delete_selection_socket, tilt_socket=None):
    """
    Converts Curve -> Wire Mesh -> Delete Points -> Mesh to Curve.
    Unlike deleting points directly on a Curve (which connects remaining ends with a straight line across gaps),
    deleting vertices on a Wire Mesh breaks the edge chain so each Bridge/Guardrail section becomes a separate spline!
    """
    n_wire = nodes.new('GeometryNodeCurveToMesh')
    links.new(curve_socket, n_wire.inputs["Curve"])
    
    n_del = nodes.new('GeometryNodeDeleteGeometry')
    n_del.domain = 'POINT'
    links.new(n_wire.outputs["Mesh"], n_del.inputs["Geometry"])
    links.new(delete_selection_socket, n_del.inputs["Selection"])
    
    n_m2c = nodes.new('GeometryNodeMeshToCurve')
    links.new(n_del.outputs["Geometry"], n_m2c.inputs["Mesh"])
    
    last_curve = n_m2c.outputs["Curve"]
    if tilt_socket:
        n_tilt = nodes.new('GeometryNodeSetCurveTilt')
        links.new(last_curve, n_tilt.inputs["Curve"])
        links.new(tilt_socket, n_tilt.inputs["Tilt"])
        last_curve = n_tilt.outputs["Curve"]
        
    n_norm = nodes.new('GeometryNodeSetCurveNormal')
    n_norm.mode = 'Z_UP'
    links.new(last_curve, n_norm.inputs["Curve"])
    return n_norm.outputs["Curve"]


def raycast_terrain_z_python(context, road_obj, world_xy_pos, default_z):
    """Raycasts the Landscape mesh from Python with a clean user warning if missing."""
    terrain_obj = None
    if road_obj.modifiers:
        mod = road_obj.modifiers[0]
        if mod.type == 'NODES' and mod.node_group:
            for item in mod.node_group.interface.items_tree:
                if item.in_out == 'INPUT' and item.name == "Terrain Target":
                    terrain_obj = mod.get(item.identifier)
                    break
    if not terrain_obj:
        terrain_obj = bpy.data.objects.get("Landscape")
        
    if not terrain_obj or terrain_obj.type != 'MESH':
        # Show a friendly, warning in Blender's info header instead of a crash traceback!
        context.window_manager.popup_menu(
            lambda self, ctx: self.layout.label(text="⚠️ Error: Please name your terrain/landscape mesh object 'Landscape'!"),
            title="Mountain Road Creator Warning",
            icon='ERROR'
        )
        return default_z
        
    depsgraph = context.evaluated_depsgraph_get()
    inv_mat = terrain_obj.matrix_world.inverted()
    ray_origin_world = Vector((world_xy_pos.x, world_xy_pos.y, world_xy_pos.z + 300.0))
    ray_origin_local = inv_mat @ ray_origin_world
    ray_dir_local = (inv_mat.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    
    success, location_local, _, _ = terrain_obj.ray_cast(ray_origin_local, ray_dir_local, distance=1000.0, depsgraph=depsgraph)
    if success:
        hit_world = terrain_obj.matrix_world @ location_local
        hit_in_road = road_obj.matrix_world.inverted() @ hit_world
        return hit_in_road.z + 0.30
    return default_z


# ==============================================================================
# AUTO-HANDLER: APPLIES ACTIVE BLUE BUTTON MODE TO NEW "DRAW CURVE" STROKES
# ==============================================================================
_last_spline_counts = {}

@persistent
def road_draw_and_clamp_handler(scene, depsgraph):
    context = bpy.context
    obj = getattr(context, "active_object", None)
    if not obj or obj.type != 'CURVE' or not obj.modifiers:
        return
    if not obj.modifiers[0].node_group or not obj.modifiers[0].node_group.name.startswith("AAA_Road_Engine"):
        return
        
    active_mode = getattr(scene, "road_active_mode", 0)
    rad_map = {0: 1.0, 1: 2.0, 2: 0.5}
    target_rad = rad_map.get(active_mode, 1.0)
    
    splines = obj.data.splines
    prev_count = _last_spline_counts.get(obj.name, len(splines))
    
    if len(splines) > prev_count:
        for sp in splines[prev_count:]:
            for pt in sp.bezier_points:
                pt.radius = target_rad
                w_pos = obj.matrix_world @ pt.co
                g_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                new_z = max(pt.co.z, g_z + 3.5) if active_mode == 1 else g_z
                dz = new_z - pt.co.z
                pt.co.z = new_z
                pt.handle_left.z += dz
                pt.handle_right.z += dz
            for pt in sp.points:
                pt.radius = target_rad
                
    _last_spline_counts[obj.name] = len(splines)


# ==============================================================================
# HELPER: LIVE BRIDGE Z-HEIGHT GETTER / SETTER (WITH ANTI-UNDERGROUND CLAMP!)
# ==============================================================================
def get_selected_points_z(self):
    obj = bpy.context.active_object
    if not obj or obj.type != 'CURVE':
        return 0.0
    vals = []
    for sp in obj.data.splines:
        if sp.type == 'BEZIER':
            for pt in sp.bezier_points:
                if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                    vals.append(pt.co.z)
        else:
            for pt in sp.points:
                if pt.select:
                    vals.append(pt.co[2])
    return sum(vals) / len(vals) if vals else 0.0


def set_selected_points_z(self, value):
    context = bpy.context
    obj = context.active_object
    if not obj or obj.type != 'CURVE':
        return
    current_avg = get_selected_points_z(self)
    delta_z = value - current_avg
    for sp in obj.data.splines:
        if sp.type == 'BEZIER':
            for pt in sp.bezier_points:
                if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                    w_pos = obj.matrix_world @ pt.co
                    min_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                    if pt.radius > 1.50:
                        clamped_z = max(pt.co.z + delta_z, min_z + 0.40)
                    else:
                        clamped_z = min_z
                    dz = clamped_z - pt.co.z
                    pt.co.z = clamped_z
                    pt.handle_left.z += dz
                    pt.handle_right.z += dz
        else:
            for pt in sp.points:
                if pt.select:
                    w_pos = obj.matrix_world @ Vector(pt.co[:3])
                    min_z = raycast_terrain_z_python(context, obj, w_pos, pt.co[2])
                    pt.co[2] = max(pt.co[2] + delta_z, min_z + 0.40) if pt.radius > 1.50 else min_z
    obj.update_tag()


def get_selected_point_mode(obj):
    if not obj or obj.type != 'CURVE' or obj.mode != 'EDIT':
        return None
    for sp in obj.data.splines:
        if sp.type == 'BEZIER':
            for pt in sp.bezier_points:
                if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                    if pt.radius > 1.50:
                        return 1
                    elif pt.radius < 0.75:
                        return 2
                    else:
                        return 0
        else:
            for pt in sp.points:
                if pt.select:
                    if pt.radius > 1.50:
                        return 1
                    elif pt.radius < 0.75:
                        return 2
                    else:
                        return 0
    return None


# ==============================================================================
# HELPER: AUTO MATERIALS (ASPHALT, DIRT, CONCRETE, OFFROAD, GUARDRAIL STEEL)
# ==============================================================================
def create_default_materials():
    mats = {}
    specs = [
        ("Road_Asphalt_Mat", (0.11, 0.11, 0.13, 1.0), 0.85, 0.0),
        ("Road_Embankment_Dirt_Mat", (0.28, 0.20, 0.13, 1.0), 0.90, 0.0),
        ("Road_Bridge_Concrete_Mat", (0.50, 0.51, 0.53, 1.0), 0.80, 0.0),
        ("Road_Offroad_Track_Mat", (0.22, 0.14, 0.08, 1.0), 0.92, 0.0),
        ("Road_Guardrail_Steel_Mat", (0.68, 0.70, 0.73, 1.0), 0.35, 0.8),
    ]
    for name, col, rough, metal in specs:
        mat = bpy.data.materials.get(name)
        if not mat:
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            nt = mat.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = col
                bsdf.inputs["Roughness"].default_value = rough
                if "Metallic" in bsdf.inputs:
                    bsdf.inputs["Metallic"].default_value = metal
                
                if name == "Road_Asphalt_Mat":
                    n_uv = nt.nodes.new('ShaderNodeAttribute')
                    n_uv.attribute_name = "UVMap"
                    n_sep = nt.nodes.new('ShaderNodeSeparateXYZ')
                    n_ramp = nt.nodes.new('ShaderNodeValToRGB')
                    n_ramp.color_ramp.interpolation = 'CONSTANT'
                    cr = n_ramp.color_ramp
                    cr.elements[0].position = 0.0
                    cr.elements[0].color = col
                    
                    e1 = cr.elements.new(0.05)
                    e1.color = (0.8, 0.8, 0.8, 1.0)
                    e2 = cr.elements.new(0.08)
                    e2.color = col
                    
                    cr.elements[1].position = 0.485
                    cr.elements[1].color = (0.95, 0.72, 0.1, 1.0)
                    
                    e3 = cr.elements.new(0.515)
                    e3.color = col
                    e4 = cr.elements.new(0.92)
                    e4.color = (0.8, 0.8, 0.8, 1.0)
                    e5 = cr.elements.new(0.95)
                    e5.color = col
                    
                    nt.links.new(n_uv.outputs["Vector"], n_sep.inputs["Vector"])
                    nt.links.new(n_sep.outputs["X"], n_ramp.inputs["Fac"])
                    nt.links.new(n_ramp.outputs["Color"], bsdf.inputs["Base Color"])
        mats[name] = mat
    return mats


# ==============================================================================
# CORE GEOMETRY NODES ENGINE (V6.3 TRUE SPLINE SPLITTING FOR BRIDGES & GUARDRAILS)
# ==============================================================================
def create_road_node_group():
    group_name = "AAA_Road_Engine_v6_3"
    if group_name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[group_name])
        
    ng = bpy.data.node_groups.new(group_name, 'GeometryNodeTree')
    
    # --- 1. CIVIL ENGINEERING PROPORTION CONTROLS ---
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    
    ng.interface.new_socket("Terrain Target", in_out='INPUT', socket_type='NodeSocketObject')
    
    s_width = ng.interface.new_socket("Road Width (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_width.default_value = 6.0
    s_width.min_value = 1.0
    
    s_camber = ng.interface.new_socket("Road Camber / Crown Height (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_camber.default_value = 0.06
    s_camber.min_value = -0.5
    s_camber.max_value = 0.5
    
    s_bank = ng.interface.new_socket("Superelevation / Banking Angle (deg)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_bank.default_value = 0.0
    s_bank.min_value = -25.0
    s_bank.max_value = 25.0
    
    s_spread = ng.interface.new_socket("Embankment Slope Spread (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_spread.default_value = 2.2
    s_spread.min_value = 0.0
    
    s_max_drop = ng.interface.new_socket("Max Embankment Drop Depth (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_max_drop.default_value = 3.0
    s_max_drop.min_value = 0.2
    
    s_height = ng.interface.new_socket("Ground Road Clearance (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_height.default_value = 0.30
    s_height.min_value = 0.05
    s_height.max_value = 1.50
    
    s_junc_flare = ng.interface.new_socket("Junction Corner Flare Width", in_out='INPUT', socket_type='NodeSocketFloat')
    s_junc_flare.default_value = 0.55
    s_junc_flare.min_value = 0.0
    s_junc_flare.max_value = 2.0
    
    s_junc_rad = ng.interface.new_socket("Intersection Wall Clear Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    s_junc_rad.default_value = 5.0
    s_junc_rad.min_value = 0.0
    
    s_res = ng.interface.new_socket("Segment Length (Poly Resolution)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_res.default_value = 1.50
    s_res.min_value = 0.25
    
    s_smooth = ng.interface.new_socket("Curve & Slope Smoothness", in_out='INPUT', socket_type='NodeSocketInt')
    s_smooth.default_value = 3
    s_smooth.min_value = 0
    s_smooth.max_value = 30
    
    s_uv_scale = ng.interface.new_socket("UV Texture Tiling Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s_uv_scale.default_value = 0.20
    s_uv_scale.min_value = 0.01

    # --- 2. GUARDRAIL / CRASH BARRIER CONTROLS ---
    s_gr_en = ng.interface.new_socket("Enable Guardrails / Crash Barriers", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_en.default_value = True
    
    s_gr_asph = ng.interface.new_socket("Guardrails on Asphalt Roads", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_asph.default_value = True
    
    s_gr_br = ng.interface.new_socket("Guardrails on Bridges", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_br.default_value = True
    
    s_gr_off = ng.interface.new_socket("Guardrails on Offroad Tracks", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_off.default_value = False
    
    s_gr_left = ng.interface.new_socket("Left Side Guardrail", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_left.default_value = True
    
    s_gr_right = ng.interface.new_socket("Right Side Guardrail", in_out='INPUT', socket_type='NodeSocketBool')
    s_gr_right.default_value = True
    
    s_gr_dist = ng.interface.new_socket("Guardrail Post Spacing (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_gr_dist.default_value = 3.0
    s_gr_dist.min_value = 1.0
    
    s_gr_off_xy = ng.interface.new_socket("Guardrail Edge Inset/Outset (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_gr_off_xy.default_value = -0.15
    s_gr_off_xy.min_value = -2.0
    s_gr_off_xy.max_value = 2.0
    
    s_gr_scale = ng.interface.new_socket("Guardrail Height / Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s_gr_scale.default_value = 1.0
    s_gr_scale.min_value = 0.1
    
    s_use_cust_gr = ng.interface.new_socket("Use Custom 3D Guardrail Mesh", in_out='INPUT', socket_type='NodeSocketBool')
    s_use_cust_gr.default_value = False
    ng.interface.new_socket("Custom 3D Guardrail Object (Mesh)", in_out='INPUT', socket_type='NodeSocketObject')

    # --- 3. BRIDGE & PILLAR CONTROLS ---
    s_pillars = ng.interface.new_socket("Enable Bridge Pillars", in_out='INPUT', socket_type='NodeSocketBool')
    s_pillars.default_value = True
    
    s_p_dist = ng.interface.new_socket("Pillar Spacing Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    s_p_dist.default_value = 10.0
    s_p_dist.min_value = 2.0
    
    s_p_rad = ng.interface.new_socket("Pillar Thickness / Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s_p_rad.default_value = 0.65
    s_p_rad.min_value = 0.1
    
    s_p_off = ng.interface.new_socket("Pillar Top Vertical Offset (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_p_off.default_value = -0.25
    s_p_off.min_value = -10.0
    s_p_off.max_value = 0.0
    
    s_wall_h = ng.interface.new_socket("Bridge Side Barrier Height", in_out='INPUT', socket_type='NodeSocketFloat')
    s_wall_h.default_value = 0.45
    s_wall_h.min_value = 0.0
    
    s_use_cust_br = ng.interface.new_socket("Use Custom 2D Bridge Profile", in_out='INPUT', socket_type='NodeSocketBool')
    s_use_cust_br.default_value = False
    ng.interface.new_socket("Custom 2D Bridge Profile (Curve)", in_out='INPUT', socket_type='NodeSocketObject')
    
    s_br_z_off = ng.interface.new_socket("2D Bridge Deck Vertical Offset (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_br_z_off.default_value = -0.08
    s_br_z_off.min_value = -5.0
    s_br_z_off.max_value = 2.0
    
    s_flip_br = ng.interface.new_socket("Flip 2D Bridge Profile Upside-Down", in_out='INPUT', socket_type='NodeSocketBool')
    s_flip_br.default_value = False
    
    s_use_cust_pil = ng.interface.new_socket("Use Custom 3D Pillar Mesh", in_out='INPUT', socket_type='NodeSocketBool')
    s_use_cust_pil.default_value = False
    ng.interface.new_socket("Custom 3D Pillar Object (Mesh)", in_out='INPUT', socket_type='NodeSocketObject')

    # --- 4. OFFROAD & MATERIAL CONTROLS ---
    s_off_noise = ng.interface.new_socket("Offroad Mud/Rock Bumpiness", in_out='INPUT', socket_type='NodeSocketFloat')
    s_off_noise.default_value = 0.25
    s_off_noise.min_value = 0.0
    
    s_off_crown = ng.interface.new_socket("Offroad Center Arch / Rut Depth", in_out='INPUT', socket_type='NodeSocketFloat')
    s_off_crown.default_value = -0.15
    s_off_crown.min_value = -1.5
    s_off_crown.max_value = 1.5

    ng.interface.new_socket("Road Surface Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Embankment Dirt Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Bridge & Pillar Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Offroad Track Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Guardrail Material", in_out='INPUT', socket_type='NodeSocketMaterial')

    nodes = ng.nodes
    links = ng.links
    n_in = nodes.new('NodeGroupInput')
    n_out = nodes.new('NodeGroupOutput')
    
    # ==========================================================================
    # STEP 1: RESAMPLE CURVE & DECODE PER-POINT SEGMENT TYPES
    # Offroad = 0.5 (< 0.75) | Asphalt = 1.0 (0.75..1.50) | Bridge = 2.0 (> 1.50)
    # ==========================================================================
    n_dom_idx = nodes.new('GeometryNodeInputIndex')
    n_store_sp_idx = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_sp_idx.data_type = 'INT'
    n_store_sp_idx.domain = 'CURVE'
    n_store_sp_idx.inputs["Name"].default_value = "sp_idx"
    links.new(n_in.outputs["Geometry"], n_store_sp_idx.inputs["Geometry"])
    links.new(n_dom_idx.outputs["Index"], n_store_sp_idx.inputs["Value"])
    
    n_resample = nodes.new('GeometryNodeResampleCurve')
    n_resample.mode = 'LENGTH'
    links.new(n_store_sp_idx.outputs["Geometry"], n_resample.inputs["Curve"])
    links.new(n_in.outputs["Segment Length (Poly Resolution)"], n_resample.inputs["Length"])
    
    n_obj = nodes.new('GeometryNodeObjectInfo')
    n_obj.transform_space = 'RELATIVE'
    links.new(n_in.outputs["Terrain Target"], n_obj.inputs["Object"])
    
    n_c_pos = nodes.new('GeometryNodeInputPosition')
    n_rad_in = nodes.new('GeometryNodeInputRadius')
    
    n_final_bridge = nodes.new('FunctionNodeCompare')
    n_final_bridge.data_type = 'FLOAT'
    n_final_bridge.operation = 'GREATER_THAN'
    n_final_bridge.inputs[1].default_value = 1.50
    links.new(n_rad_in.outputs["Radius"], n_final_bridge.inputs[0])
    
    n_final_offroad = nodes.new('FunctionNodeCompare')
    n_final_offroad.data_type = 'FLOAT'
    n_final_offroad.operation = 'LESS_THAN'
    n_final_offroad.inputs[1].default_value = 0.75
    links.new(n_rad_in.outputs["Radius"], n_final_offroad.inputs[0])
    
    n_not_br = nodes.new('FunctionNodeBooleanMath')
    n_not_br.operation = 'NOT'
    links.new(n_final_bridge.outputs["Result"], n_not_br.inputs[0])
    
    n_store_br = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_br.data_type = 'BOOLEAN'
    n_store_br.domain = 'POINT'
    n_store_br.inputs["Name"].default_value = "is_bridge"
    links.new(n_resample.outputs["Curve"], n_store_br.inputs["Geometry"])
    links.new(n_final_bridge.outputs["Result"], n_store_br.inputs["Value"])
    
    n_store_off = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_off.data_type = 'BOOLEAN'
    n_store_off.domain = 'POINT'
    n_store_off.inputs["Name"].default_value = "is_offroad"
    links.new(n_store_br.outputs["Geometry"], n_store_off.inputs["Geometry"])
    links.new(n_final_offroad.outputs["Result"], n_store_off.inputs["Value"])
    
    n_rad_reset = nodes.new('GeometryNodeSetCurveRadius')
    n_rad_reset.inputs["Radius"].default_value = 1.0
    links.new(n_store_off.outputs["Geometry"], n_rad_reset.inputs["Curve"])
    
    n_in_tilt = nodes.new('GeometryNodeInputCurveTilt')
    n_bank_rad = nodes.new('ShaderNodeMath')
    n_bank_rad.operation = 'RADIANS'
    links.new(n_in.outputs["Superelevation / Banking Angle (deg)"], n_bank_rad.inputs[0])
    
    n_total_tilt = nodes.new('ShaderNodeMath')
    n_total_tilt.operation = 'ADD'
    links.new(n_in_tilt.outputs["Tilt"], n_total_tilt.inputs[0])
    links.new(n_bank_rad.outputs["Value"], n_total_tilt.inputs[1])
    
    n_tilt_set = nodes.new('GeometryNodeSetCurveTilt')
    links.new(n_rad_reset.outputs["Curve"], n_tilt_set.inputs["Curve"])
    links.new(n_total_tilt.outputs["Value"], n_tilt_set.inputs["Tilt"])
    
    n_norm_z = nodes.new('GeometryNodeSetCurveNormal')
    n_norm_z.mode = 'Z_UP'
    links.new(n_tilt_set.outputs["Curve"], n_norm_z.inputs["Curve"])

    # ==========================================================================
    # STEP 2: STRICT TERRAIN RULES (ASPHALT/OFFROAD STICK TO TERRAIN;
    # BRIDGE MOVES UP FREELY BUT NEVER GOES UNDERGROUND INTO TERRAIN!)
    # ==========================================================================
    n_ray_center = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    
    n_sep_orig_c = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c_pos.outputs["Position"], n_sep_orig_c.inputs["Vector"])
    
    n_sep_hit_c = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_center.outputs["Hit Position"], n_sep_hit_c.inputs["Vector"])
    
    n_ground_target_z = nodes.new('ShaderNodeMath')
    n_ground_target_z.operation = 'ADD'
    links.new(n_sep_hit_c.outputs["Z"], n_ground_target_z.inputs[0])
    links.new(n_in.outputs["Ground Road Clearance (m)"], n_ground_target_z.inputs[1])
    
    n_br_min_z = nodes.new('ShaderNodeMath')
    n_br_min_z.operation = 'ADD'
    n_br_min_z.inputs[1].default_value = 0.15
    links.new(n_ground_target_z.outputs["Value"], n_br_min_z.inputs[0])
    
    n_clamped_br_z = nodes.new('ShaderNodeMath')
    n_clamped_br_z.operation = 'MAXIMUM'
    links.new(n_sep_orig_c.outputs["Z"], n_clamped_br_z.inputs[0])
    links.new(n_br_min_z.outputs["Value"], n_clamped_br_z.inputs[1])
    
    n_read_br_step2 = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_step2.data_type = 'BOOLEAN'
    n_read_br_step2.inputs["Name"].default_value = "is_bridge"
    
    n_sw_target_z = nodes.new('GeometryNodeSwitch')
    n_sw_target_z.input_type = 'FLOAT'
    links.new(n_read_br_step2.outputs["Attribute"], n_sw_target_z.inputs["Switch"])
    links.new(n_ground_target_z.outputs["Value"], n_sw_target_z.inputs["False"])
    links.new(n_clamped_br_z.outputs["Value"], n_sw_target_z.inputs["True"])
    
    n_comb_c_pos = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_sep_orig_c.outputs["X"], n_comb_c_pos.inputs["X"])
    links.new(n_sep_orig_c.outputs["Y"], n_comb_c_pos.inputs["Y"])
    links.new(n_sw_target_z.outputs["Output"], n_comb_c_pos.inputs["Z"])
    
    n_set_c_pos = nodes.new('GeometryNodeSetPosition')
    links.new(n_norm_z.outputs["Curve"], n_set_c_pos.inputs["Geometry"])
    links.new(n_ray_center.outputs["Is Hit"], n_set_c_pos.inputs["Selection"])
    links.new(n_comb_c_pos.outputs["Vector"], n_set_c_pos.inputs["Position"])
    
    n_end_sel = nodes.new('GeometryNodeCurveEndpointSelection')
    n_end_sel.inputs["Start Size"].default_value = 1
    n_end_sel.inputs["End Size"].default_value = 1
    
    n_not_end = nodes.new('FunctionNodeBooleanMath')
    n_not_end.operation = 'NOT'
    links.new(n_end_sel.outputs["Selection"], n_not_end.inputs[0])
    
    n_blur = nodes.new('GeometryNodeBlurAttribute')
    n_blur.data_type = 'FLOAT_VECTOR'
    links.new(n_c_pos.outputs["Position"], n_blur.inputs["Value"])
    links.new(n_in.outputs["Curve & Slope Smoothness"], n_blur.inputs["Iterations"])
    
    n_smooth_c_raw = nodes.new('GeometryNodeSetPosition')
    links.new(n_set_c_pos.outputs["Geometry"], n_smooth_c_raw.inputs["Geometry"])
    links.new(n_not_end.outputs["Boolean"], n_smooth_c_raw.inputs["Selection"])
    links.new(n_blur.outputs["Value"], n_smooth_c_raw.inputs["Position"])
    
    n_ray_post = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    n_sep_post_c = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c_pos.outputs["Position"], n_sep_post_c.inputs["Vector"])
    n_sep_post_hit = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_post.outputs["Hit Position"], n_sep_post_hit.inputs["Vector"])
    
    n_post_ground_z = nodes.new('ShaderNodeMath')
    n_post_ground_z.operation = 'ADD'
    links.new(n_sep_post_hit.outputs["Z"], n_post_ground_z.inputs[0])
    links.new(n_in.outputs["Ground Road Clearance (m)"], n_post_ground_z.inputs[1])
    
    n_post_safe_z = nodes.new('ShaderNodeMath')
    n_post_safe_z.operation = 'MAXIMUM'
    links.new(n_sep_post_c.outputs["Z"], n_post_safe_z.inputs[0])
    links.new(n_post_ground_z.outputs["Value"], n_post_safe_z.inputs[1])
    
    n_comb_post_pos = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_sep_post_c.outputs["X"], n_comb_post_pos.inputs["X"])
    links.new(n_sep_post_c.outputs["Y"], n_comb_post_pos.inputs["Y"])
    links.new(n_post_safe_z.outputs["Value"], n_comb_post_pos.inputs["Z"])
    
    n_smooth_c = nodes.new('GeometryNodeSetPosition')
    links.new(n_smooth_c_raw.outputs["Geometry"], n_smooth_c.inputs["Geometry"])
    links.new(n_ray_post.outputs["Is Hit"], n_smooth_c.inputs["Selection"])
    links.new(n_comb_post_pos.outputs["Vector"], n_smooth_c.inputs["Position"])

    # ==========================================================================
    # STEP 2B: NON-OVERLAPPING T-JUNCTION TRIM & BELL-MOUTH CORNER FLARE
    # ==========================================================================
    n_read_sp_idx_c = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_sp_idx_c.data_type = 'INT'
    n_read_sp_idx_c.inputs["Name"].default_value = "sp_idx"
    
    n_is_main_sp = nodes.new('FunctionNodeCompare')
    n_is_main_sp.data_type = 'INT'
    n_is_main_sp.operation = 'EQUAL'
    n_is_main_sp.inputs[3].default_value = 0
    links.new(n_read_sp_idx_c.outputs["Attribute"], n_is_main_sp.inputs[2])
    
    n_is_branch_sp = nodes.new('FunctionNodeCompare')
    n_is_branch_sp.data_type = 'INT'
    n_is_branch_sp.operation = 'GREATER_THAN'
    n_is_branch_sp.inputs[3].default_value = 0
    links.new(n_read_sp_idx_c.outputs["Attribute"], n_is_branch_sp.inputs[2])
    
    n_sep_main = nodes.new('GeometryNodeSeparateGeometry')
    n_sep_main.domain = 'CURVE'
    links.new(n_smooth_c.outputs["Geometry"], n_sep_main.inputs["Geometry"])
    links.new(n_is_main_sp.outputs["Result"], n_sep_main.inputs["Selection"])
    
    n_main_wire = nodes.new('GeometryNodeCurveToMesh')
    links.new(n_sep_main.outputs["Selection"], n_main_wire.inputs["Curve"])
    
    n_dummy_line = nodes.new('GeometryNodeMeshLine')
    n_dummy_line.inputs["Count"].default_value = 2
    n_dummy_line.inputs["Start Location"].default_value = (0.0, 0.0, -99999.0)
    n_dummy_line.inputs["Offset"].default_value = (0.0, 0.0, -1.0)
    
    n_join_main_target = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_main_wire.outputs["Mesh"], n_join_main_target.inputs["Geometry"])
    links.new(n_dummy_line.outputs["Mesh"], n_join_main_target.inputs["Geometry"])
    
    n_prox_main = nodes.new('GeometryNodeProximity')
    n_prox_main.target_element = 'EDGES'
    links.new(n_join_main_target.outputs["Geometry"], n_prox_main.inputs["Target"])
    
    n_half_w = nodes.new('ShaderNodeMath')
    n_half_w.operation = 'MULTIPLY'
    n_half_w.inputs[1].default_value = 0.5
    links.new(n_in.outputs["Road Width (m)"], n_half_w.inputs[0])
    
    n_trim_thresh = nodes.new('ShaderNodeMath')
    n_trim_thresh.operation = 'MULTIPLY'
    n_trim_thresh.inputs[1].default_value = 0.35
    links.new(n_in.outputs["Road Width (m)"], n_trim_thresh.inputs[0])
    
    n_too_close_main = nodes.new('FunctionNodeCompare')
    n_too_close_main.data_type = 'FLOAT'
    n_too_close_main.operation = 'LESS_THAN'
    links.new(n_prox_main.outputs["Distance"], n_too_close_main.inputs[0])
    links.new(n_trim_thresh.outputs["Value"], n_too_close_main.inputs[1])
    
    n_del_overlap_cond = nodes.new('FunctionNodeBooleanMath')
    n_del_overlap_cond.operation = 'AND'
    links.new(n_is_branch_sp.outputs["Result"], n_del_overlap_cond.inputs[0])
    links.new(n_too_close_main.outputs["Result"], n_del_overlap_cond.inputs[1])
    
    # Use wire-mesh split so trimming a crossing road inside the main road splits it cleanly into 2 branches!
    trimmed_curve_out = split_curve_by_deleting_points(
        nodes, links,
        n_smooth_c.outputs["Geometry"],
        n_del_overlap_cond.outputs["Boolean"],
        n_bank_rad.outputs["Value"]
    )
    
    n_prox_main2 = nodes.new('GeometryNodeProximity')
    n_prox_main2.target_element = 'EDGES'
    links.new(n_join_main_target.outputs["Geometry"], n_prox_main2.inputs["Target"])
    
    n_flare_zone = nodes.new('ShaderNodeMath')
    n_flare_zone.operation = 'MULTIPLY'
    n_flare_zone.inputs[1].default_value = 1.25
    links.new(n_in.outputs["Road Width (m)"], n_flare_zone.inputs[0])
    
    n_map_flare = nodes.new('ShaderNodeMapRange')
    n_map_flare.clamp = True
    n_map_flare.inputs["To Min"].default_value = 1.0
    n_map_flare.inputs["To Max"].default_value = 0.0
    links.new(n_prox_main2.outputs["Distance"], n_map_flare.inputs["Value"])
    links.new(n_trim_thresh.outputs["Value"], n_map_flare.inputs["From Min"])
    links.new(n_flare_zone.outputs["Value"], n_map_flare.inputs["From Max"])
    
    n_flare_sq = nodes.new('ShaderNodeMath')
    n_flare_sq.operation = 'MULTIPLY'
    links.new(n_map_flare.outputs["Result"], n_flare_sq.inputs[0])
    links.new(n_map_flare.outputs["Result"], n_flare_sq.inputs[1])
    
    n_flare_amt = nodes.new('ShaderNodeMath')
    n_flare_amt.operation = 'MULTIPLY'
    links.new(n_flare_sq.outputs["Value"], n_flare_amt.inputs[0])
    links.new(n_in.outputs["Junction Corner Flare Width"], n_flare_amt.inputs[1])
    
    n_flare_rad = nodes.new('ShaderNodeMath')
    n_flare_rad.operation = 'ADD'
    n_flare_rad.inputs[0].default_value = 1.0
    links.new(n_flare_amt.outputs["Value"], n_flare_rad.inputs[1])
    
    n_read_sp_trimmed = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_sp_trimmed.data_type = 'INT'
    n_read_sp_trimmed.inputs["Name"].default_value = "sp_idx"
    
    n_is_br_trimmed = nodes.new('FunctionNodeCompare')
    n_is_br_trimmed.data_type = 'INT'
    n_is_br_trimmed.operation = 'GREATER_THAN'
    n_is_br_trimmed.inputs[3].default_value = 0
    links.new(n_read_sp_trimmed.outputs["Attribute"], n_is_br_trimmed.inputs[2])
    
    n_sw_curve_rad = nodes.new('GeometryNodeSwitch')
    n_sw_curve_rad.input_type = 'FLOAT'
    n_sw_curve_rad.inputs["False"].default_value = 1.0
    links.new(n_is_br_trimmed.outputs["Result"], n_sw_curve_rad.inputs["Switch"])
    links.new(n_flare_rad.outputs["Value"], n_sw_curve_rad.inputs["True"])
    
    n_apply_flare_rad = nodes.new('GeometryNodeSetCurveRadius')
    links.new(trimmed_curve_out, n_apply_flare_rad.inputs["Curve"])
    links.new(n_sw_curve_rad.outputs["Output"], n_apply_flare_rad.inputs["Radius"])
    
    n_norm_z2 = nodes.new('GeometryNodeSetCurveNormal')
    n_norm_z2.mode = 'Z_UP'
    links.new(n_apply_flare_rad.outputs["Curve"], n_norm_z2.inputs["Curve"])
    
    n_sp_len = nodes.new('GeometryNodeSplineParameter')
    n_uv_v_math = nodes.new('ShaderNodeMath')
    n_uv_v_math.operation = 'MULTIPLY'
    links.new(n_sp_len.outputs["Length"], n_uv_v_math.inputs[0])
    links.new(n_in.outputs["UV Texture Tiling Scale"], n_uv_v_math.inputs[1])
    
    n_store_v = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_v.data_type = 'FLOAT'
    n_store_v.domain = 'POINT'
    n_store_v.inputs["Name"].default_value = "uv_v"
    links.new(n_norm_z2.outputs["Curve"], n_store_v.inputs["Geometry"])
    links.new(n_uv_v_math.outputs["Value"], n_store_v.inputs["Value"])

    # ==========================================================================
    # STEP 2C: BUILD INTERSECTION CLEARING POINT CLOUD
    # ==========================================================================
    n_junc_end_sel = nodes.new('GeometryNodeCurveEndpointSelection')
    n_junc_end_sel.inputs["Start Size"].default_value = 3
    n_junc_end_sel.inputs["End Size"].default_value = 3
    
    n_cross_thresh = nodes.new('ShaderNodeMath')
    n_cross_thresh.operation = 'MULTIPLY'
    n_cross_thresh.inputs[1].default_value = 1.15
    links.new(n_in.outputs["Road Width (m)"], n_cross_thresh.inputs[0])
    
    n_near_main_cross = nodes.new('FunctionNodeCompare')
    n_near_main_cross.data_type = 'FLOAT'
    n_near_main_cross.operation = 'LESS_THAN'
    links.new(n_prox_main2.outputs["Distance"], n_near_main_cross.inputs[0])
    links.new(n_cross_thresh.outputs["Value"], n_near_main_cross.inputs[1])
    
    n_end_or_cross = nodes.new('FunctionNodeBooleanMath')
    n_end_or_cross.operation = 'OR'
    links.new(n_junc_end_sel.outputs["Selection"], n_end_or_cross.inputs[0])
    links.new(n_near_main_cross.outputs["Result"], n_end_or_cross.inputs[1])
    
    n_junc_pt_sel = nodes.new('FunctionNodeBooleanMath')
    n_junc_pt_sel.operation = 'AND'
    links.new(n_end_or_cross.outputs["Boolean"], n_junc_pt_sel.inputs[0])
    links.new(n_is_br_trimmed.outputs["Result"], n_junc_pt_sel.inputs[1])
    
    n_not_junc_pt = nodes.new('FunctionNodeBooleanMath')
    n_not_junc_pt.operation = 'NOT'
    links.new(n_junc_pt_sel.outputs["Boolean"], n_not_junc_pt.inputs[0])
    
    n_junc_pts = nodes.new('GeometryNodeCurveToPoints')
    n_junc_pts.mode = 'EVALUATED'
    links.new(n_norm_z2.outputs["Curve"], n_junc_pts.inputs["Curve"])
    
    n_del_non_junc = nodes.new('GeometryNodeDeleteGeometry')
    n_del_non_junc.domain = 'POINT'
    links.new(n_junc_pts.outputs["Points"], n_del_non_junc.inputs["Geometry"])
    links.new(n_not_junc_pt.outputs["Boolean"], n_del_non_junc.inputs["Selection"])
    
    n_dummy_c2p = nodes.new('GeometryNodeMeshToPoints')
    links.new(n_dummy_line.outputs["Mesh"], n_dummy_c2p.inputs["Mesh"])
    
    n_join_junc_cloud = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_del_non_junc.outputs["Geometry"], n_join_junc_cloud.inputs["Geometry"])
    links.new(n_dummy_c2p.outputs["Points"], n_join_junc_cloud.inputs["Geometry"])

    # ==========================================================================
    # STEP 3: BUILD TRUE 9-POINT SYMMETRIC CROSS-SECTION PROFILE
    # ==========================================================================
    n_neg_half_w = nodes.new('ShaderNodeMath')
    n_neg_half_w.operation = 'MULTIPLY'
    n_neg_half_w.inputs[1].default_value = -1.0
    links.new(n_half_w.outputs["Value"], n_neg_half_w.inputs[0])
    
    n_p_start = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_neg_half_w.outputs["Value"], n_p_start.inputs["X"])
    n_p_end = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_half_w.outputs["Value"], n_p_end.inputs["X"])
    
    n_prof_line = nodes.new('GeometryNodeCurvePrimitiveLine')
    links.new(n_p_start.outputs["Vector"], n_prof_line.inputs["Start"])
    links.new(n_p_end.outputs["Vector"], n_prof_line.inputs["End"])
    
    n_res_prof = nodes.new('GeometryNodeResampleCurve')
    n_res_prof.mode = 'COUNT'
    n_res_prof.inputs["Count"].default_value = 9
    links.new(n_prof_line.outputs["Curve"], n_res_prof.inputs["Curve"])
    
    n_idx = nodes.new('GeometryNodeInputIndex')
    
    n_is_idx0 = nodes.new('FunctionNodeCompare')
    n_is_idx0.data_type = 'INT'
    n_is_idx0.operation = 'EQUAL'
    n_is_idx0.inputs[3].default_value = 0
    links.new(n_idx.outputs["Index"], n_is_idx0.inputs[2])
    
    n_is_idx8 = nodes.new('FunctionNodeCompare')
    n_is_idx8.data_type = 'INT'
    n_is_idx8.operation = 'EQUAL'
    n_is_idx8.inputs[3].default_value = 8
    links.new(n_idx.outputs["Index"], n_is_idx8.inputs[2])
    
    n_is_skirt_pt = nodes.new('FunctionNodeBooleanMath')
    n_is_skirt_pt.operation = 'OR'
    links.new(n_is_idx0.outputs["Result"], n_is_skirt_pt.inputs[0])
    links.new(n_is_idx8.outputs["Result"], n_is_skirt_pt.inputs[1])
    
    n_idx_sub1 = nodes.new('ShaderNodeMath')
    n_idx_sub1.operation = 'SUBTRACT'
    n_idx_sub1.inputs[1].default_value = 1.0
    links.new(n_idx.outputs["Index"], n_idx_sub1.inputs[0])
    
    n_t_road = nodes.new('ShaderNodeMath')
    n_t_road.operation = 'DIVIDE'
    n_t_road.inputs[1].default_value = 6.0
    links.new(n_idx_sub1.outputs["Value"], n_t_road.inputs[0])
    
    n_t_sym = nodes.new('ShaderNodeMath')
    n_t_sym.operation = 'MULTIPLY_ADD'
    n_t_sym.inputs[1].default_value = 2.0
    n_t_sym.inputs[2].default_value = -1.0
    links.new(n_t_road.outputs["Value"], n_t_sym.inputs[0])
    
    n_inner_x = nodes.new('ShaderNodeMath')
    n_inner_x.operation = 'MULTIPLY'
    links.new(n_t_sym.outputs["Value"], n_inner_x.inputs[0])
    links.new(n_half_w.outputs["Value"], n_inner_x.inputs[1])
    
    n_outer_dist = nodes.new('ShaderNodeMath')
    n_outer_dist.operation = 'ADD'
    links.new(n_half_w.outputs["Value"], n_outer_dist.inputs[0])
    links.new(n_in.outputs["Embankment Slope Spread (m)"], n_outer_dist.inputs[1])
    
    n_neg_outer = nodes.new('ShaderNodeMath')
    n_neg_outer.operation = 'MULTIPLY'
    n_neg_outer.inputs[1].default_value = -1.0
    links.new(n_outer_dist.outputs["Value"], n_neg_outer.inputs[0])
    
    n_sw_left = nodes.new('GeometryNodeSwitch')
    n_sw_left.input_type = 'FLOAT'
    links.new(n_is_idx0.outputs["Result"], n_sw_left.inputs["Switch"])
    links.new(n_inner_x.outputs["Value"], n_sw_left.inputs["False"])
    links.new(n_neg_outer.outputs["Value"], n_sw_left.inputs["True"])
    
    n_sw_right = nodes.new('GeometryNodeSwitch')
    n_sw_right.input_type = 'FLOAT'
    links.new(n_is_idx8.outputs["Result"], n_sw_right.inputs["Switch"])
    links.new(n_sw_left.outputs["Output"], n_sw_right.inputs["False"])
    links.new(n_outer_dist.outputs["Value"], n_sw_right.inputs["True"])
    
    n_prof_pos_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_sw_right.outputs["Output"], n_prof_pos_vec.inputs["X"])
    
    n_set_prof_pos = nodes.new('GeometryNodeSetPosition')
    links.new(n_res_prof.outputs["Curve"], n_set_prof_pos.inputs["Geometry"])
    links.new(n_prof_pos_vec.outputs["Vector"], n_set_prof_pos.inputs["Position"])
    
    n_store_skirt = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_skirt.data_type = 'BOOLEAN'
    n_store_skirt.domain = 'POINT'
    n_store_skirt.inputs["Name"].default_value = "is_skirt"
    links.new(n_set_prof_pos.outputs["Geometry"], n_store_skirt.inputs["Geometry"])
    links.new(n_is_skirt_pt.outputs["Boolean"], n_store_skirt.inputs["Value"])
    
    n_store_u = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_u.data_type = 'FLOAT'
    n_store_u.domain = 'POINT'
    n_store_u.inputs["Name"].default_value = "uv_u"
    links.new(n_store_skirt.outputs["Geometry"], n_store_u.inputs["Geometry"])
    links.new(n_t_road.outputs["Value"], n_store_u.inputs["Value"])

    # ==========================================================================
    # STEP 4: SWEEP CURVE TO MESH & STORE UVMAP
    # ==========================================================================
    n_c2m = nodes.new('GeometryNodeCurveToMesh')
    links.new(n_store_v.outputs["Geometry"], n_c2m.inputs["Curve"])
    links.new(n_store_u.outputs["Geometry"], n_c2m.inputs["Profile Curve"])
    
    n_read_u = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_u.data_type = 'FLOAT'
    n_read_u.inputs["Name"].default_value = "uv_u"
    
    n_read_v = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_v.data_type = 'FLOAT'
    n_read_v.inputs["Name"].default_value = "uv_v"
    
    n_comb_uv = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_read_u.outputs["Attribute"], n_comb_uv.inputs["X"])
    links.new(n_read_v.outputs["Attribute"], n_comb_uv.inputs["Y"])
    
    n_store_uv = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_uv.data_type = 'FLOAT2'
    n_store_uv.domain = 'CORNER'
    n_store_uv.inputs["Name"].default_value = "UVMap"
    links.new(n_c2m.outputs["Mesh"], n_store_uv.inputs["Geometry"])
    links.new(n_comb_uv.outputs["Vector"], n_store_uv.inputs["Value"])

    # ==========================================================================
    # STEP 5: CIVIL ENGINEERING VERTEX ELEVATION
    # ==========================================================================
    n_ray_mesh = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    
    n_m_pos = nodes.new('GeometryNodeInputPosition')
    n_sep_m = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_m_pos.outputs["Position"], n_sep_m.inputs["Vector"])
    
    n_sep_mhit = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_mesh.outputs["Hit Position"], n_sep_mhit.inputs["Vector"])
    
    n_u_remap = nodes.new('ShaderNodeMath')
    n_u_remap.operation = 'MULTIPLY_ADD'
    n_u_remap.inputs[1].default_value = 2.0
    n_u_remap.inputs[2].default_value = -1.0
    links.new(n_read_u.outputs["Attribute"], n_u_remap.inputs[0])
    
    n_u_sq = nodes.new('ShaderNodeMath')
    n_u_sq.operation = 'MULTIPLY'
    links.new(n_u_remap.outputs["Value"], n_u_sq.inputs[0])
    links.new(n_u_remap.outputs["Value"], n_u_sq.inputs[1])
    
    n_arch = nodes.new('ShaderNodeMath')
    n_arch.operation = 'SUBTRACT'
    n_arch.inputs[0].default_value = 1.0
    links.new(n_u_sq.outputs["Value"], n_arch.inputs[1])
    
    n_asph_camber = nodes.new('ShaderNodeMath')
    n_asph_camber.operation = 'MULTIPLY'
    links.new(n_arch.outputs["Value"], n_asph_camber.inputs[0])
    links.new(n_in.outputs["Road Camber / Crown Height (m)"], n_asph_camber.inputs[1])
    
    n_level_asphalt_z = nodes.new('ShaderNodeMath')
    n_level_asphalt_z.operation = 'ADD'
    links.new(n_sep_m.outputs["Z"], n_level_asphalt_z.inputs[0])
    links.new(n_asph_camber.outputs["Value"], n_level_asphalt_z.inputs[1])
    
    n_crown_z = nodes.new('ShaderNodeMath')
    n_crown_z.operation = 'MULTIPLY'
    links.new(n_arch.outputs["Value"], n_crown_z.inputs[0])
    links.new(n_in.outputs["Offroad Center Arch / Rut Depth"], n_crown_z.inputs[1])
    
    n_noise = nodes.new('ShaderNodeTexNoise')
    n_noise.inputs["Scale"].default_value = 1.8
    n_noise.inputs["Detail"].default_value = 4.0
    n_noise_sub = nodes.new('ShaderNodeMath')
    n_noise_sub.operation = 'SUBTRACT'
    n_noise_sub.inputs[1].default_value = 0.5
    links.new(n_noise.outputs["Fac"], n_noise_sub.inputs[0])
    
    n_noise_z = nodes.new('ShaderNodeMath')
    n_noise_z.operation = 'MULTIPLY'
    links.new(n_noise_sub.outputs["Value"], n_noise_z.inputs[0])
    links.new(n_in.outputs["Offroad Mud/Rock Bumpiness"], n_noise_z.inputs[1])
    
    n_off_disp = nodes.new('ShaderNodeMath')
    n_off_disp.operation = 'ADD'
    links.new(n_crown_z.outputs["Value"], n_off_disp.inputs[0])
    links.new(n_noise_z.outputs["Value"], n_off_disp.inputs[1])
    
    n_level_offroad_z = nodes.new('ShaderNodeMath')
    n_level_offroad_z.operation = 'ADD'
    links.new(n_sep_m.outputs["Z"], n_level_offroad_z.inputs[0])
    links.new(n_off_disp.outputs["Value"], n_level_offroad_z.inputs[1])
    
    n_read_br_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_m.data_type = 'BOOLEAN'
    n_read_br_m.inputs["Name"].default_value = "is_bridge"
    
    n_read_off_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_off_m.data_type = 'BOOLEAN'
    n_read_off_m.inputs["Name"].default_value = "is_offroad"
    
    n_read_skirt_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_skirt_m.data_type = 'BOOLEAN'
    n_read_skirt_m.inputs["Name"].default_value = "is_skirt"
    
    n_sw_surf_z = nodes.new('GeometryNodeSwitch')
    n_sw_surf_z.input_type = 'FLOAT'
    links.new(n_read_off_m.outputs["Attribute"], n_sw_surf_z.inputs["Switch"])
    links.new(n_level_asphalt_z.outputs["Value"], n_sw_surf_z.inputs["False"])
    links.new(n_level_offroad_z.outputs["Value"], n_sw_surf_z.inputs["True"])
    
    n_sw_bridge_surf_z = nodes.new('GeometryNodeSwitch')
    n_sw_bridge_surf_z.input_type = 'FLOAT'
    links.new(n_read_br_m.outputs["Attribute"], n_sw_bridge_surf_z.inputs["Switch"])
    links.new(n_sw_surf_z.outputs["Output"], n_sw_bridge_surf_z.inputs["False"])
    links.new(n_level_asphalt_z.outputs["Value"], n_sw_bridge_surf_z.inputs["True"])
    
    n_prox_junc = nodes.new('GeometryNodeProximity')
    n_prox_junc.target_element = 'POINTS'
    links.new(n_join_junc_cloud.outputs["Geometry"], n_prox_junc.inputs["Target"])
    
    n_in_junc = nodes.new('FunctionNodeCompare')
    n_in_junc.data_type = 'FLOAT'
    n_in_junc.operation = 'LESS_THAN'
    links.new(n_prox_junc.outputs["Distance"], n_in_junc.inputs[0])
    links.new(n_in.outputs["Intersection Wall Clear Radius"], n_in_junc.inputs[1])
    
    n_eff_wall_h = nodes.new('GeometryNodeSwitch')
    n_eff_wall_h.input_type = 'FLOAT'
    n_eff_wall_h.inputs["True"].default_value = 0.0
    links.new(n_in_junc.outputs["Result"], n_eff_wall_h.inputs["Switch"])
    links.new(n_in.outputs["Bridge Side Barrier Height"], n_eff_wall_h.inputs["False"])
    
    n_skirt_raw_ground = nodes.new('ShaderNodeMath')
    n_skirt_raw_ground.operation = 'SUBTRACT'
    n_skirt_raw_ground.inputs[1].default_value = 0.35
    links.new(n_sep_mhit.outputs["Z"], n_skirt_raw_ground.inputs[0])
    
    n_skirt_max_drop = nodes.new('ShaderNodeMath')
    n_skirt_max_drop.operation = 'SUBTRACT'
    links.new(n_sep_m.outputs["Z"], n_skirt_max_drop.inputs[0])
    links.new(n_in.outputs["Max Embankment Drop Depth (m)"], n_skirt_max_drop.inputs[1])
    
    n_skirt_min_drop = nodes.new('ShaderNodeMath')
    n_skirt_min_drop.operation = 'SUBTRACT'
    n_skirt_min_drop.inputs[1].default_value = 0.25
    links.new(n_sep_m.outputs["Z"], n_skirt_min_drop.inputs[0])
    
    n_skirt_clamp_low = nodes.new('ShaderNodeMath')
    n_skirt_clamp_low.operation = 'MAXIMUM'
    links.new(n_skirt_raw_ground.outputs["Value"], n_skirt_clamp_low.inputs[0])
    links.new(n_skirt_max_drop.outputs["Value"], n_skirt_clamp_low.inputs[1])
    
    n_skirt_ground_z = nodes.new('ShaderNodeMath')
    n_skirt_ground_z.operation = 'MINIMUM'
    links.new(n_skirt_clamp_low.outputs["Value"], n_skirt_ground_z.inputs[0])
    links.new(n_skirt_min_drop.outputs["Value"], n_skirt_ground_z.inputs[1])
    
    n_skirt_junc_z = nodes.new('ShaderNodeMath')
    n_skirt_junc_z.operation = 'SUBTRACT'
    n_skirt_junc_z.inputs[1].default_value = 0.08
    links.new(n_sep_m.outputs["Z"], n_skirt_junc_z.inputs[0])
    
    n_sw_ground_junc_z = nodes.new('GeometryNodeSwitch')
    n_sw_ground_junc_z.input_type = 'FLOAT'
    links.new(n_in_junc.outputs["Result"], n_sw_ground_junc_z.inputs["Switch"])
    links.new(n_skirt_ground_z.outputs["Value"], n_sw_ground_junc_z.inputs["False"])
    links.new(n_skirt_junc_z.outputs["Value"], n_sw_ground_junc_z.inputs["True"])
        
    n_skirt_bridge_z = nodes.new('ShaderNodeMath')
    n_skirt_bridge_z.operation = 'ADD'
    links.new(n_sep_m.outputs["Z"], n_skirt_bridge_z.inputs[0])
    links.new(n_eff_wall_h.outputs["Output"], n_skirt_bridge_z.inputs[1])
    
    n_sw_skirt_z = nodes.new('GeometryNodeSwitch')
    n_sw_skirt_z.input_type = 'FLOAT'
    links.new(n_read_br_m.outputs["Attribute"], n_sw_skirt_z.inputs["Switch"])
    links.new(n_sw_ground_junc_z.outputs["Output"], n_sw_skirt_z.inputs["False"])
    links.new(n_skirt_bridge_z.outputs["Value"], n_sw_skirt_z.inputs["True"])
    
    n_final_z = nodes.new('GeometryNodeSwitch')
    n_final_z.input_type = 'FLOAT'
    links.new(n_read_skirt_m.outputs["Attribute"], n_final_z.inputs["Switch"])
    links.new(n_sw_bridge_surf_z.outputs["Output"], n_final_z.inputs["False"])
    links.new(n_sw_skirt_z.outputs["Output"], n_final_z.inputs["True"])
    
    n_br_or_junc = nodes.new('FunctionNodeBooleanMath')
    n_br_or_junc.operation = 'OR'
    links.new(n_read_br_m.outputs["Attribute"], n_br_or_junc.inputs[0])
    links.new(n_in_junc.outputs["Result"], n_br_or_junc.inputs[1])
    
    n_pull_skirt_cond = nodes.new('FunctionNodeBooleanMath')
    n_pull_skirt_cond.operation = 'AND'
    links.new(n_read_skirt_m.outputs["Attribute"], n_pull_skirt_cond.inputs[0])
    links.new(n_br_or_junc.outputs["Boolean"], n_pull_skirt_cond.inputs[1])
    
    n_prox_curve_mesh = nodes.new('GeometryNodeCurveToMesh')
    links.new(n_norm_z2.outputs["Curve"], n_prox_curve_mesh.inputs["Curve"])
    
    n_prox_curve = nodes.new('GeometryNodeProximity')
    n_prox_curve.target_element = 'EDGES'
    links.new(n_prox_curve_mesh.outputs["Mesh"], n_prox_curve.inputs["Target"])

    n_dir_from_c = nodes.new('ShaderNodeVectorMath')
    n_dir_from_c.operation = 'SUBTRACT'
    links.new(n_m_pos.outputs["Position"], n_dir_from_c.inputs[0])
    links.new(n_prox_curve.outputs["Position"], n_dir_from_c.inputs[1])
    
    n_norm_from_c = nodes.new('ShaderNodeVectorMath')
    n_norm_from_c.operation = 'NORMALIZE'
    links.new(n_dir_from_c.outputs["Vector"], n_norm_from_c.inputs[0])
    
    n_wall_outer_dist = nodes.new('ShaderNodeMath')
    n_wall_outer_dist.operation = 'ADD'
    n_wall_outer_dist.inputs[1].default_value = 0.20
    links.new(n_half_w.outputs["Value"], n_wall_outer_dist.inputs[0])
    
    n_scaled_wall_xy = nodes.new('ShaderNodeVectorMath')
    n_scaled_wall_xy.operation = 'SCALE'
    links.new(n_norm_from_c.outputs["Vector"], n_scaled_wall_xy.inputs["Vector"])
    links.new(n_wall_outer_dist.outputs["Value"], n_scaled_wall_xy.inputs["Scale"])
    
    n_tight_xy = nodes.new('ShaderNodeVectorMath')
    n_tight_xy.operation = 'ADD'
    links.new(n_prox_curve.outputs["Position"], n_tight_xy.inputs[0])
    links.new(n_scaled_wall_xy.outputs["Vector"], n_tight_xy.inputs[1])
    
    n_sw_xy = nodes.new('GeometryNodeSwitch')
    n_sw_xy.input_type = 'VECTOR'
    links.new(n_pull_skirt_cond.outputs["Boolean"], n_sw_xy.inputs["Switch"])
    links.new(n_m_pos.outputs["Position"], n_sw_xy.inputs["False"])
    links.new(n_tight_xy.outputs["Vector"], n_sw_xy.inputs["True"])
    
    n_sep_final_xy = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_sw_xy.outputs["Output"], n_sep_final_xy.inputs["Vector"])
    
    n_final_pos = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_sep_final_xy.outputs["X"], n_final_pos.inputs["X"])
    links.new(n_sep_final_xy.outputs["Y"], n_final_pos.inputs["Y"])
    links.new(n_final_z.outputs["Output"], n_final_pos.inputs["Z"])
    
    n_set_all_pos = nodes.new('GeometryNodeSetPosition')
    links.new(n_store_uv.outputs["Geometry"], n_set_all_pos.inputs["Geometry"])
    links.new(n_final_pos.outputs["Vector"], n_set_all_pos.inputs["Position"])

    # ==========================================================================
    # STEP 6: ASSIGN SURFACE & EMBANKMENT MATERIALS
    # ==========================================================================
    n_mat_asphalt = nodes.new('GeometryNodeSetMaterial')
    links.new(n_set_all_pos.outputs["Geometry"], n_mat_asphalt.inputs["Geometry"])
    links.new(n_in.outputs["Road Surface Material"], n_mat_asphalt.inputs["Material"])
    
    n_mat_offroad = nodes.new('GeometryNodeSetMaterial')
    links.new(n_mat_asphalt.outputs["Geometry"], n_mat_offroad.inputs["Geometry"])
    links.new(n_read_off_m.outputs["Attribute"], n_mat_offroad.inputs["Selection"])
    links.new(n_in.outputs["Offroad Track Material"], n_mat_offroad.inputs["Material"])
    
    n_mat_bank = nodes.new('GeometryNodeSetMaterial')
    links.new(n_mat_offroad.outputs["Geometry"], n_mat_bank.inputs["Geometry"])
    links.new(n_read_skirt_m.outputs["Attribute"], n_mat_bank.inputs["Selection"])
    links.new(n_in.outputs["Embankment Dirt Material"], n_mat_bank.inputs["Material"])
    
    n_br_skirt_and = nodes.new('FunctionNodeBooleanMath')
    n_br_skirt_and.operation = 'AND'
    links.new(n_read_skirt_m.outputs["Attribute"], n_br_skirt_and.inputs[0])
    links.new(n_read_br_m.outputs["Attribute"], n_br_skirt_and.inputs[1])
    
    n_mat_br_wall = nodes.new('GeometryNodeSetMaterial')
    links.new(n_mat_bank.outputs["Geometry"], n_mat_br_wall.inputs["Geometry"])
    links.new(n_br_skirt_and.outputs["Boolean"], n_mat_br_wall.inputs["Selection"])
    links.new(n_in.outputs["Bridge & Pillar Material"], n_mat_br_wall.inputs["Material"])

    # ==========================================================================
    # STEP 6B: SPLIT BRIDGE CURVES VIA WIRE MESH SO MULTIPLE BRIDGES NEVER CONNECT ACROSS OFFROAD!
    # ==========================================================================
    n_read_br_curve = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_curve.data_type = 'BOOLEAN'
    n_read_br_curve.inputs["Name"].default_value = "is_bridge"
    
    n_not_br_curve = nodes.new('FunctionNodeBooleanMath')
    n_not_br_curve.operation = 'NOT'
    links.new(n_read_br_curve.outputs["Attribute"], n_not_br_curve.inputs[0])
    
    only_bridge_curve_out = split_curve_by_deleting_points(
        nodes, links,
        n_norm_z2.outputs["Curve"],
        n_not_br_curve.outputs["Boolean"],
        n_bank_rad.outputs["Value"]
    )
    
    n_cust_br_info = nodes.new('GeometryNodeObjectInfo')
    n_cust_br_info.transform_space = 'ORIGINAL'
    links.new(n_in.outputs["Custom 2D Bridge Profile (Curve)"], n_cust_br_info.inputs["Object"])
    
    n_br_bbox = nodes.new('GeometryNodeBoundBox')
    links.new(n_cust_br_info.outputs["Geometry"], n_br_bbox.inputs["Geometry"])
    
    n_sep_br_min = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_br_bbox.outputs["Min"], n_sep_br_min.inputs["Vector"])
    n_sep_br_max = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_br_bbox.outputs["Max"], n_sep_br_max.inputs["Vector"])
    
    n_prof_w = nodes.new('ShaderNodeMath')
    n_prof_w.operation = 'SUBTRACT'
    links.new(n_sep_br_max.outputs["X"], n_prof_w.inputs[0])
    links.new(n_sep_br_min.outputs["X"], n_prof_w.inputs[1])
    
    n_safe_pw = nodes.new('ShaderNodeMath')
    n_safe_pw.operation = 'MAXIMUM'
    n_safe_pw.inputs[1].default_value = 0.01
    links.new(n_prof_w.outputs["Value"], n_safe_pw.inputs[0])
    
    n_scale_pw = nodes.new('ShaderNodeMath')
    n_scale_pw.operation = 'DIVIDE'
    links.new(n_in.outputs["Road Width (m)"], n_scale_pw.inputs[0])
    links.new(n_safe_pw.outputs["Value"], n_scale_pw.inputs[1])
    
    n_sw_flip_y = nodes.new('GeometryNodeSwitch')
    n_sw_flip_y.input_type = 'FLOAT'
    n_sw_flip_y.inputs["False"].default_value = 1.0
    n_sw_flip_y.inputs["True"].default_value = -1.0
    links.new(n_in.outputs["Flip 2D Bridge Profile Upside-Down"], n_sw_flip_y.inputs["Switch"])
    
    n_prof_scale_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_scale_pw.outputs["Value"], n_prof_scale_vec.inputs["X"])
    links.new(n_sw_flip_y.outputs["Output"], n_prof_scale_vec.inputs["Y"])
    n_prof_scale_vec.inputs["Z"].default_value = 1.0
    
    n_trans_prof_2d = nodes.new('GeometryNodeTransform')
    links.new(n_cust_br_info.outputs["Geometry"], n_trans_prof_2d.inputs["Geometry"])
    links.new(n_prof_scale_vec.outputs["Vector"], n_trans_prof_2d.inputs["Scale"])
    
    n_br_z_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_in.outputs["2D Bridge Deck Vertical Offset (m)"], n_br_z_vec.inputs["Z"])
    
    n_offset_br_curve = nodes.new('GeometryNodeSetPosition')
    links.new(only_bridge_curve_out, n_offset_br_curve.inputs["Geometry"])
    links.new(n_br_z_vec.outputs["Vector"], n_offset_br_curve.inputs["Offset"])

    n_c2m_cust_br = nodes.new('GeometryNodeCurveToMesh')
    n_c2m_cust_br.inputs["Fill Caps"].default_value = True
    links.new(n_offset_br_curve.outputs["Geometry"], n_c2m_cust_br.inputs["Curve"])
    links.new(n_trans_prof_2d.outputs["Geometry"], n_c2m_cust_br.inputs["Profile Curve"])
    
    n_mat_cust_br = nodes.new('GeometryNodeSetMaterial')
    links.new(n_c2m_cust_br.outputs["Mesh"], n_mat_cust_br.inputs["Geometry"])
    links.new(n_in.outputs["Bridge & Pillar Material"], n_mat_cust_br.inputs["Material"])
    
    n_sw_cust_br = nodes.new('GeometryNodeSwitch')
    n_sw_cust_br.input_type = 'GEOMETRY'
    links.new(n_in.outputs["Use Custom 2D Bridge Profile"], n_sw_cust_br.inputs["Switch"])
    links.new(n_mat_cust_br.outputs["Geometry"], n_sw_cust_br.inputs["True"])

    # ==========================================================================
    # STEP 7: BRIDGE SUPPORT PILLARS (ON TRUE SPLIT BRIDGE SPLINES)
    # ==========================================================================
    n_c2p_pillars = nodes.new('GeometryNodeCurveToPoints')
    n_c2p_pillars.mode = 'LENGTH'
    links.new(only_bridge_curve_out, n_c2p_pillars.inputs["Curve"])
    links.new(n_in.outputs["Pillar Spacing Distance"], n_c2p_pillars.inputs["Length"])
    
    n_prox_p_junc = nodes.new('GeometryNodeProximity')
    n_prox_p_junc.target_element = 'POINTS'
    links.new(n_join_junc_cloud.outputs["Geometry"], n_prox_p_junc.inputs["Target"])
    
    n_p_not_junc = nodes.new('FunctionNodeCompare')
    n_p_not_junc.data_type = 'FLOAT'
    n_p_not_junc.operation = 'GREATER_THAN'
    links.new(n_prox_p_junc.outputs["Distance"], n_p_not_junc.inputs[0])
    links.new(n_in.outputs["Intersection Wall Clear Radius"], n_p_not_junc.inputs[1])
    
    n_ray_pillar = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    n_p_pos = nodes.new('GeometryNodeInputPosition')
    n_sep_p = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_p_pos.outputs["Position"], n_sep_p.inputs["Vector"])
    n_sep_phit = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_pillar.outputs["Hit Position"], n_sep_phit.inputs["Vector"])
    
    n_p_height = nodes.new('ShaderNodeMath')
    n_p_height.operation = 'SUBTRACT'
    links.new(n_sep_p.outputs["Z"], n_p_height.inputs[0])
    links.new(n_sep_phit.outputs["Z"], n_p_height.inputs[1])
    
    n_p_high_enough = nodes.new('FunctionNodeCompare')
    n_p_high_enough.data_type = 'FLOAT'
    n_p_high_enough.operation = 'GREATER_THAN'
    n_p_high_enough.inputs[1].default_value = 0.60
    links.new(n_p_height.outputs["Value"], n_p_high_enough.inputs[0])
    
    n_p_sel1 = nodes.new('FunctionNodeBooleanMath')
    n_p_sel1.operation = 'AND'
    links.new(n_in.outputs["Enable Bridge Pillars"], n_p_sel1.inputs[0])
    links.new(n_p_not_junc.outputs["Result"], n_p_sel1.inputs[1])
    
    n_p_sel = nodes.new('FunctionNodeBooleanMath')
    n_p_sel.operation = 'AND'
    links.new(n_p_sel1.outputs["Boolean"], n_p_sel.inputs[0])
    links.new(n_p_high_enough.outputs["Result"], n_p_sel.inputs[1])
    
    n_cyl = nodes.new('GeometryNodeMeshCylinder')
    n_cyl.inputs["Vertices"].default_value = 12
    n_cyl.inputs["Depth"].default_value = 1.0
    links.new(n_in.outputs["Pillar Thickness / Scale"], n_cyl.inputs["Radius"])
    
    n_trans_cyl = nodes.new('GeometryNodeTransform')
    n_trans_cyl.inputs["Translation"].default_value = (0.0, 0.0, -0.5)
    links.new(n_cyl.outputs["Mesh"], n_trans_cyl.inputs["Geometry"])
    
    n_mat_def_pil = nodes.new('GeometryNodeSetMaterial')
    links.new(n_trans_cyl.outputs["Geometry"], n_mat_def_pil.inputs["Geometry"])
    links.new(n_in.outputs["Bridge & Pillar Material"], n_mat_def_pil.inputs["Material"])
    
    n_cust_pil_info = nodes.new('GeometryNodeObjectInfo')
    n_cust_pil_info.transform_space = 'ORIGINAL'
    links.new(n_in.outputs["Custom 3D Pillar Object (Mesh)"], n_cust_pil_info.inputs["Object"])
    
    n_bbox = nodes.new('GeometryNodeBoundBox')
    links.new(n_cust_pil_info.outputs["Geometry"], n_bbox.inputs["Geometry"])
    
    n_sep_bmin = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_bbox.outputs["Min"], n_sep_bmin.inputs["Vector"])
    n_sep_bmax = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_bbox.outputs["Max"], n_sep_bmax.inputs["Vector"])
    
    n_neg_max_z = nodes.new('ShaderNodeMath')
    n_neg_max_z.operation = 'MULTIPLY'
    n_neg_max_z.inputs[1].default_value = -1.0
    links.new(n_sep_bmax.outputs["Z"], n_neg_max_z.inputs[0])
    
    n_shift_top_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_neg_max_z.outputs["Value"], n_shift_top_vec.inputs["Z"])
    
    n_trans_cust_top = nodes.new('GeometryNodeTransform')
    links.new(n_cust_pil_info.outputs["Geometry"], n_trans_cust_top.inputs["Geometry"])
    links.new(n_shift_top_vec.outputs["Vector"], n_trans_cust_top.inputs["Translation"])
    
    n_b_height = nodes.new('ShaderNodeMath')
    n_b_height.operation = 'SUBTRACT'
    links.new(n_sep_bmax.outputs["Z"], n_b_height.inputs[0])
    links.new(n_sep_bmin.outputs["Z"], n_b_height.inputs[1])
    
    n_safe_bh = nodes.new('ShaderNodeMath')
    n_safe_bh.operation = 'MAXIMUM'
    n_safe_bh.inputs[1].default_value = 0.01
    links.new(n_b_height.outputs["Value"], n_safe_bh.inputs[0])
    
    n_inv_bh = nodes.new('ShaderNodeMath')
    n_inv_bh.operation = 'DIVIDE'
    n_inv_bh.inputs[0].default_value = 1.0
    links.new(n_safe_bh.outputs["Value"], n_inv_bh.inputs[1])
    
    n_norm_cust_scale = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_in.outputs["Pillar Thickness / Scale"], n_norm_cust_scale.inputs["X"])
    links.new(n_in.outputs["Pillar Thickness / Scale"], n_norm_cust_scale.inputs["Y"])
    links.new(n_inv_bh.outputs["Value"], n_norm_cust_scale.inputs["Z"])
    
    n_trans_cust_norm = nodes.new('GeometryNodeTransform')
    links.new(n_trans_cust_top.outputs["Geometry"], n_trans_cust_norm.inputs["Geometry"])
    links.new(n_norm_cust_scale.outputs["Vector"], n_trans_cust_norm.inputs["Scale"])
    
    n_sw_pil_mesh = nodes.new('GeometryNodeSwitch')
    n_sw_pil_mesh.input_type = 'GEOMETRY'
    links.new(n_in.outputs["Use Custom 3D Pillar Mesh"], n_sw_pil_mesh.inputs["Switch"])
    links.new(n_mat_def_pil.outputs["Geometry"], n_sw_pil_mesh.inputs["False"])
    links.new(n_trans_cust_norm.outputs["Geometry"], n_sw_pil_mesh.inputs["True"])
    
    n_pil_off_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_in.outputs["Pillar Top Vertical Offset (m)"], n_pil_off_vec.inputs["Z"])
    
    n_recess_p = nodes.new('GeometryNodeSetPosition')
    links.new(n_c2p_pillars.outputs["Points"], n_recess_p.inputs["Geometry"])
    links.new(n_pil_off_vec.outputs["Vector"], n_recess_p.inputs["Offset"])
    
    n_sep_tan_p = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c2p_pillars.outputs["Tangent"], n_sep_tan_p.inputs["Vector"])
    n_yaw_p = nodes.new('ShaderNodeMath')
    n_yaw_p.operation = 'ARCTAN2'
    links.new(n_sep_tan_p.outputs["Y"], n_yaw_p.inputs[0])
    links.new(n_sep_tan_p.outputs["X"], n_yaw_p.inputs[1])
    n_rot_p = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_yaw_p.outputs["Value"], n_rot_p.inputs["Z"])
    
    n_p_height_sink = nodes.new('ShaderNodeMath')
    n_p_height_sink.operation = 'ADD'
    n_p_height_sink.inputs[1].default_value = 0.5
    links.new(n_p_height.outputs["Value"], n_p_height_sink.inputs[0])
    
    n_p_scale = nodes.new('ShaderNodeCombineXYZ')
    n_p_scale.inputs["X"].default_value = 1.0
    n_p_scale.inputs["Y"].default_value = 1.0
    links.new(n_p_height_sink.outputs["Value"], n_p_scale.inputs["Z"])
    
    n_inst_p = nodes.new('GeometryNodeInstanceOnPoints')
    links.new(n_recess_p.outputs["Geometry"], n_inst_p.inputs["Points"])
    links.new(n_p_sel.outputs["Boolean"], n_inst_p.inputs["Selection"])
    links.new(n_sw_pil_mesh.outputs["Output"], n_inst_p.inputs["Instance"])
    links.new(n_rot_p.outputs["Vector"], n_inst_p.inputs["Rotation"])
    links.new(n_p_scale.outputs["Vector"], n_inst_p.inputs["Scale"])
    
    n_realize_p = nodes.new('GeometryNodeRealizeInstances')
    links.new(n_inst_p.outputs["Instances"], n_realize_p.inputs["Geometry"])

    # ==========================================================================
    # STEP 8: SPLIT GUARDRAIL CURVES VIA WIRE MESH SO GUARDRAILS NEVER SHOOT ACROSS OFFROAD OR JUNCTIONS!
    # ==========================================================================
    n_gr_is_asph1 = nodes.new('FunctionNodeBooleanMath')
    n_gr_is_asph1.operation = 'NOT'
    links.new(n_read_off_m.outputs["Attribute"], n_gr_is_asph1.inputs[0])
    
    n_gr_is_asph = nodes.new('FunctionNodeBooleanMath')
    n_gr_is_asph.operation = 'AND'
    links.new(n_not_br_curve.outputs["Boolean"], n_gr_is_asph.inputs[0])
    links.new(n_gr_is_asph1.outputs["Boolean"], n_gr_is_asph.inputs[1])
    
    n_gr_allow_asph = nodes.new('FunctionNodeBooleanMath')
    n_gr_allow_asph.operation = 'AND'
    links.new(n_gr_is_asph.outputs["Boolean"], n_gr_allow_asph.inputs[0])
    links.new(n_in.outputs["Guardrails on Asphalt Roads"], n_gr_allow_asph.inputs[1])
    
    n_gr_allow_br = nodes.new('FunctionNodeBooleanMath')
    n_gr_allow_br.operation = 'AND'
    links.new(n_read_br_curve.outputs["Attribute"], n_gr_allow_br.inputs[0])
    links.new(n_in.outputs["Guardrails on Bridges"], n_gr_allow_br.inputs[1])
    
    n_gr_allow_off = nodes.new('FunctionNodeBooleanMath')
    n_gr_allow_off.operation = 'AND'
    links.new(n_read_off_m.outputs["Attribute"], n_gr_allow_off.inputs[0])
    links.new(n_in.outputs["Guardrails on Offroad Tracks"], n_gr_allow_off.inputs[1])
    
    n_gr_or1 = nodes.new('FunctionNodeBooleanMath')
    n_gr_or1.operation = 'OR'
    links.new(n_gr_allow_asph.outputs["Boolean"], n_gr_or1.inputs[0])
    links.new(n_gr_allow_br.outputs["Boolean"], n_gr_or1.inputs[1])
    
    n_gr_seg_valid = nodes.new('FunctionNodeBooleanMath')
    n_gr_seg_valid.operation = 'OR'
    links.new(n_gr_or1.outputs["Boolean"], n_gr_seg_valid.inputs[0])
    links.new(n_gr_allow_off.outputs["Boolean"], n_gr_seg_valid.inputs[1])
    
    n_prox_gr_c_junc = nodes.new('GeometryNodeProximity')
    n_prox_gr_c_junc.target_element = 'POINTS'
    links.new(n_join_junc_cloud.outputs["Geometry"], n_prox_gr_c_junc.inputs["Target"])
    
    n_gr_clear_rad = nodes.new('ShaderNodeMath')
    n_gr_clear_rad.operation = 'ADD'
    links.new(n_in.outputs["Intersection Wall Clear Radius"], n_gr_clear_rad.inputs[0])
    links.new(n_half_w.outputs["Value"], n_gr_clear_rad.inputs[1])
    
    n_gr_c_outside_junc = nodes.new('FunctionNodeCompare')
    n_gr_c_outside_junc.data_type = 'FLOAT'
    n_gr_c_outside_junc.operation = 'GREATER_THAN'
    links.new(n_prox_gr_c_junc.outputs["Distance"], n_gr_c_outside_junc.inputs[0])
    links.new(n_gr_clear_rad.outputs["Value"], n_gr_c_outside_junc.inputs[1])
    
    n_gr_keep_pt = nodes.new('FunctionNodeBooleanMath')
    n_gr_keep_pt.operation = 'AND'
    links.new(n_gr_seg_valid.outputs["Boolean"], n_gr_keep_pt.inputs[0])
    links.new(n_gr_c_outside_junc.outputs["Result"], n_gr_keep_pt.inputs[1])
    
    n_gr_del_pt = nodes.new('FunctionNodeBooleanMath')
    n_gr_del_pt.operation = 'NOT'
    links.new(n_gr_keep_pt.outputs["Boolean"], n_gr_del_pt.inputs[0])
    
    # Split Guardrail Curve via Wire Mesh so Guardrails NEVER connect across Offroad or Intersections!
    gr_valid_curve_out = split_curve_by_deleting_points(
        nodes, links,
        n_norm_z2.outputs["Curve"],
        n_gr_del_pt.outputs["Boolean"],
        n_bank_rad.outputs["Value"]
    )
    
    n_c_tan_gr = nodes.new('GeometryNodeInputTangent')
    n_up_vec = nodes.new('FunctionNodeInputVector')
    n_up_vec.vector = (0.0, 0.0, 1.0)
    
    n_cross_side = nodes.new('ShaderNodeVectorMath')
    n_cross_side.operation = 'CROSS_PRODUCT'
    links.new(n_c_tan_gr.outputs["Tangent"], n_cross_side.inputs[0])
    links.new(n_up_vec.outputs["Vector"], n_cross_side.inputs[1])
    
    n_norm_side = nodes.new('ShaderNodeVectorMath')
    n_norm_side.operation = 'NORMALIZE'
    links.new(n_cross_side.outputs["Vector"], n_norm_side.inputs[0])
    
    n_gr_edge_dist = nodes.new('ShaderNodeMath')
    n_gr_edge_dist.operation = 'ADD'
    links.new(n_half_w.outputs["Value"], n_gr_edge_dist.inputs[0])
    links.new(n_in.outputs["Guardrail Edge Inset/Outset (m)"], n_gr_edge_dist.inputs[1])
    
    n_neg_gr_dist = nodes.new('ShaderNodeMath')
    n_neg_gr_dist.operation = 'MULTIPLY'
    n_neg_gr_dist.inputs[1].default_value = -1.0
    links.new(n_gr_edge_dist.outputs["Value"], n_neg_gr_dist.inputs[0])
    
    n_right_off_vec = nodes.new('ShaderNodeVectorMath')
    n_right_off_vec.operation = 'SCALE'
    links.new(n_norm_side.outputs["Vector"], n_right_off_vec.inputs["Vector"])
    links.new(n_gr_edge_dist.outputs["Value"], n_right_off_vec.inputs["Scale"])
    
    n_left_off_vec = nodes.new('ShaderNodeVectorMath')
    n_left_off_vec.operation = 'SCALE'
    links.new(n_norm_side.outputs["Vector"], n_left_off_vec.inputs["Vector"])
    links.new(n_neg_gr_dist.outputs["Value"], n_left_off_vec.inputs["Scale"])
    
    n_curve_right = nodes.new('GeometryNodeSetPosition')
    links.new(gr_valid_curve_out, n_curve_right.inputs["Geometry"])
    links.new(n_right_off_vec.outputs["Vector"], n_curve_right.inputs["Offset"])
    
    n_curve_left = nodes.new('GeometryNodeSetPosition')
    links.new(gr_valid_curve_out, n_curve_left.inputs["Geometry"])
    links.new(n_left_off_vec.outputs["Vector"], n_curve_left.inputs["Offset"])
    
    n_rail_prof = nodes.new('GeometryNodeCurvePrimitiveQuadrilateral')
    n_rail_prof.mode = 'RECTANGLE'
    n_rail_prof.inputs["Width"].default_value = 0.08
    n_rail_prof.inputs["Height"].default_value = 0.26
    
    n_rail_z_off = nodes.new('ShaderNodeMath')
    n_rail_z_off.operation = 'MULTIPLY'
    n_rail_z_off.inputs[1].default_value = -0.62
    links.new(n_in.outputs["Guardrail Height / Scale"], n_rail_z_off.inputs[0])
    
    n_rail_prof_pos = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_rail_z_off.outputs["Value"], n_rail_prof_pos.inputs["Y"])
    
    n_trans_rail_prof = nodes.new('GeometryNodeTransform')
    links.new(n_rail_prof.outputs["Curve"], n_trans_rail_prof.inputs["Geometry"])
    links.new(n_rail_prof_pos.outputs["Vector"], n_trans_rail_prof.inputs["Translation"])
    
    n_sweep_rail_r = nodes.new('GeometryNodeCurveToMesh')
    n_sweep_rail_r.inputs["Fill Caps"].default_value = True
    links.new(n_curve_right.outputs["Geometry"], n_sweep_rail_r.inputs["Curve"])
    links.new(n_trans_rail_prof.outputs["Geometry"], n_sweep_rail_r.inputs["Profile Curve"])
    
    n_sweep_rail_l = nodes.new('GeometryNodeCurveToMesh')
    n_sweep_rail_l.inputs["Fill Caps"].default_value = True
    links.new(n_curve_left.outputs["Geometry"], n_sweep_rail_l.inputs["Curve"])
    links.new(n_trans_rail_prof.outputs["Geometry"], n_sweep_rail_l.inputs["Profile Curve"])
    
    n_c2p_gr_r = nodes.new('GeometryNodeCurveToPoints')
    n_c2p_gr_r.mode = 'LENGTH'
    links.new(n_curve_right.outputs["Geometry"], n_c2p_gr_r.inputs["Curve"])
    links.new(n_in.outputs["Guardrail Post Spacing (m)"], n_c2p_gr_r.inputs["Length"])
    
    n_c2p_gr_l = nodes.new('GeometryNodeCurveToPoints')
    n_c2p_gr_l.mode = 'LENGTH'
    links.new(n_curve_left.outputs["Geometry"], n_c2p_gr_l.inputs["Curve"])
    links.new(n_in.outputs["Guardrail Post Spacing (m)"], n_c2p_gr_l.inputs["Length"])
    
    n_sep_tan_r = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c2p_gr_r.outputs["Tangent"], n_sep_tan_r.inputs["Vector"])
    n_yaw_r = nodes.new('ShaderNodeMath')
    n_yaw_r.operation = 'ARCTAN2'
    links.new(n_sep_tan_r.outputs["Y"], n_yaw_r.inputs[0])
    links.new(n_sep_tan_r.outputs["X"], n_yaw_r.inputs[1])
    n_rot_gr_r = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_yaw_r.outputs["Value"], n_rot_gr_r.inputs["Z"])
    
    n_sep_tan_l = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c2p_gr_l.outputs["Tangent"], n_sep_tan_l.inputs["Vector"])
    n_yaw_l = nodes.new('ShaderNodeMath')
    n_yaw_l.operation = 'ARCTAN2'
    links.new(n_sep_tan_l.outputs["Y"], n_yaw_l.inputs[0])
    links.new(n_sep_tan_l.outputs["X"], n_yaw_l.inputs[1])
    n_rot_gr_l = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_yaw_l.outputs["Value"], n_rot_gr_l.inputs["Z"])
    
    n_gr_post = nodes.new('GeometryNodeMeshCube')
    n_gr_post.inputs["Size"].default_value = (0.14, 0.14, 0.82)
    n_trans_post = nodes.new('GeometryNodeTransform')
    n_trans_post.inputs["Translation"].default_value = (0.0, 0.0, 0.38)
    links.new(n_gr_post.outputs["Mesh"], n_trans_post.inputs["Geometry"])
    
    n_mat_proc_post = nodes.new('GeometryNodeSetMaterial')
    links.new(n_trans_post.outputs["Geometry"], n_mat_proc_post.inputs["Geometry"])
    links.new(n_in.outputs["Guardrail Material"], n_mat_proc_post.inputs["Material"])
    
    n_cust_gr_info = nodes.new('GeometryNodeObjectInfo')
    n_cust_gr_info.transform_space = 'ORIGINAL'
    links.new(n_in.outputs["Custom 3D Guardrail Object (Mesh)"], n_cust_gr_info.inputs["Object"])
    
    n_gr_bbox = nodes.new('GeometryNodeBoundBox')
    links.new(n_cust_gr_info.outputs["Geometry"], n_gr_bbox.inputs["Geometry"])
    
    n_sep_gmin = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_gr_bbox.outputs["Min"], n_sep_gmin.inputs["Vector"])
    n_sep_gmax = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_gr_bbox.outputs["Max"], n_sep_gmax.inputs["Vector"])
    
    n_gr_len_x = nodes.new('ShaderNodeMath')
    n_gr_len_x.operation = 'SUBTRACT'
    links.new(n_sep_gmax.outputs["X"], n_gr_len_x.inputs[0])
    links.new(n_sep_gmin.outputs["X"], n_gr_len_x.inputs[1])
    
    n_safe_gx = nodes.new('ShaderNodeMath')
    n_safe_gx.operation = 'MAXIMUM'
    n_safe_gx.inputs[1].default_value = 0.05
    links.new(n_gr_len_x.outputs["Value"], n_safe_gx.inputs[0])
    
    n_scale_gx = nodes.new('ShaderNodeMath')
    n_scale_gx.operation = 'DIVIDE'
    links.new(n_in.outputs["Guardrail Post Spacing (m)"], n_scale_gx.inputs[0])
    links.new(n_safe_gx.outputs["Value"], n_scale_gx.inputs[1])
    
    n_cust_gr_scale_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_scale_gx.outputs["Value"], n_cust_gr_scale_vec.inputs["X"])
    links.new(n_in.outputs["Guardrail Height / Scale"], n_cust_gr_scale_vec.inputs["Y"])
    links.new(n_in.outputs["Guardrail Height / Scale"], n_cust_gr_scale_vec.inputs["Z"])
    
    n_trans_cust_gr = nodes.new('GeometryNodeTransform')
    links.new(n_cust_gr_info.outputs["Geometry"], n_trans_cust_gr.inputs["Geometry"])
    links.new(n_cust_gr_scale_vec.outputs["Vector"], n_trans_cust_gr.inputs["Scale"])
    
    n_sw_gr_unit = nodes.new('GeometryNodeSwitch')
    n_sw_gr_unit.input_type = 'GEOMETRY'
    links.new(n_in.outputs["Use Custom 3D Guardrail Mesh"], n_sw_gr_unit.inputs["Switch"])
    links.new(n_mat_proc_post.outputs["Geometry"], n_sw_gr_unit.inputs["False"])
    links.new(n_trans_cust_gr.outputs["Geometry"], n_sw_gr_unit.inputs["True"])
    
    n_gr_right_sel = nodes.new('FunctionNodeBooleanMath')
    n_gr_right_sel.operation = 'AND'
    links.new(n_in.outputs["Enable Guardrails / Crash Barriers"], n_gr_right_sel.inputs[0])
    links.new(n_in.outputs["Right Side Guardrail"], n_gr_right_sel.inputs[1])
    
    n_gr_left_sel = nodes.new('FunctionNodeBooleanMath')
    n_gr_left_sel.operation = 'AND'
    links.new(n_in.outputs["Enable Guardrails / Crash Barriers"], n_gr_left_sel.inputs[0])
    links.new(n_in.outputs["Left Side Guardrail"], n_gr_left_sel.inputs[1])
    
    n_gr_scale_r = nodes.new('ShaderNodeCombineXYZ')
    n_gr_scale_r.inputs["X"].default_value = 1.0
    links.new(n_in.outputs["Guardrail Height / Scale"], n_gr_scale_r.inputs["Y"])
    links.new(n_in.outputs["Guardrail Height / Scale"], n_gr_scale_r.inputs["Z"])
    
    n_neg_gr_scale = nodes.new('ShaderNodeMath')
    n_neg_gr_scale.operation = 'MULTIPLY'
    n_neg_gr_scale.inputs[1].default_value = -1.0
    links.new(n_in.outputs["Guardrail Height / Scale"], n_neg_gr_scale.inputs[0])
    
    n_gr_scale_l = nodes.new('ShaderNodeCombineXYZ')
    n_gr_scale_l.inputs["X"].default_value = 1.0
    links.new(n_neg_gr_scale.outputs["Value"], n_gr_scale_l.inputs["Y"])
    links.new(n_in.outputs["Guardrail Height / Scale"], n_gr_scale_l.inputs["Z"])
    
    n_inst_gr_r = nodes.new('GeometryNodeInstanceOnPoints')
    links.new(n_c2p_gr_r.outputs["Points"], n_inst_gr_r.inputs["Points"])
    links.new(n_gr_right_sel.outputs["Boolean"], n_inst_gr_r.inputs["Selection"])
    links.new(n_sw_gr_unit.outputs["Output"], n_inst_gr_r.inputs["Instance"])
    links.new(n_rot_gr_r.outputs["Vector"], n_inst_gr_r.inputs["Rotation"])
    links.new(n_gr_scale_r.outputs["Vector"], n_inst_gr_r.inputs["Scale"])
    
    n_inst_gr_l = nodes.new('GeometryNodeInstanceOnPoints')
    links.new(n_c2p_gr_l.outputs["Points"], n_inst_gr_l.inputs["Points"])
    links.new(n_gr_left_sel.outputs["Boolean"], n_inst_gr_l.inputs["Selection"])
    links.new(n_sw_gr_unit.outputs["Output"], n_inst_gr_l.inputs["Instance"])
    links.new(n_rot_gr_l.outputs["Vector"], n_inst_gr_l.inputs["Rotation"])
    links.new(n_gr_scale_l.outputs["Vector"], n_inst_gr_l.inputs["Scale"])
    
    n_not_cust_gr = nodes.new('FunctionNodeBooleanMath')
    n_not_cust_gr.operation = 'NOT'
    links.new(n_in.outputs["Use Custom 3D Guardrail Mesh"], n_not_cust_gr.inputs[0])
    
    n_show_rail_r = nodes.new('FunctionNodeBooleanMath')
    n_show_rail_r.operation = 'AND'
    links.new(n_gr_right_sel.outputs["Boolean"], n_show_rail_r.inputs[0])
    links.new(n_not_cust_gr.outputs["Boolean"], n_show_rail_r.inputs[1])
    
    n_show_rail_l = nodes.new('FunctionNodeBooleanMath')
    n_show_rail_l.operation = 'AND'
    links.new(n_gr_left_sel.outputs["Boolean"], n_show_rail_l.inputs[0])
    links.new(n_not_cust_gr.outputs["Boolean"], n_show_rail_l.inputs[1])
    
    n_sw_rail_r = nodes.new('GeometryNodeSwitch')
    n_sw_rail_r.input_type = 'GEOMETRY'
    links.new(n_show_rail_r.outputs["Boolean"], n_sw_rail_r.inputs["Switch"])
    links.new(n_sweep_rail_r.outputs["Mesh"], n_sw_rail_r.inputs["True"])
    
    n_sw_rail_l = nodes.new('GeometryNodeSwitch')
    n_sw_rail_l.input_type = 'GEOMETRY'
    links.new(n_show_rail_l.outputs["Boolean"], n_sw_rail_l.inputs["Switch"])
    links.new(n_sweep_rail_l.outputs["Mesh"], n_sw_rail_l.inputs["True"])
    
    n_join_rails = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_sw_rail_r.outputs["Output"], n_join_rails.inputs["Geometry"])
    links.new(n_sw_rail_l.outputs["Output"], n_join_rails.inputs["Geometry"])
    
    n_mat_rails = nodes.new('GeometryNodeSetMaterial')
    links.new(n_join_rails.outputs["Geometry"], n_mat_rails.inputs["Geometry"])
    links.new(n_in.outputs["Guardrail Material"], n_mat_rails.inputs["Material"])
    
    n_join_gr = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_inst_gr_r.outputs["Instances"], n_join_gr.inputs["Geometry"])
    links.new(n_inst_gr_l.outputs["Instances"], n_join_gr.inputs["Geometry"])
    links.new(n_mat_rails.outputs["Geometry"], n_join_gr.inputs["Geometry"])
    
    n_realize_gr = nodes.new('GeometryNodeRealizeInstances')
    links.new(n_join_gr.outputs["Geometry"], n_realize_gr.inputs["Geometry"])
    
    n_join_all = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_mat_br_wall.outputs["Geometry"], n_join_all.inputs["Geometry"])
    links.new(n_sw_cust_br.outputs["Output"], n_join_all.inputs["Geometry"])
    links.new(n_realize_p.outputs["Geometry"], n_join_all.inputs["Geometry"])
    links.new(n_realize_gr.outputs["Geometry"], n_join_all.inputs["Geometry"])
    
    n_shade = nodes.new('GeometryNodeSetShadeSmooth')
    n_shade.inputs["Shade Smooth"].default_value = False
    links.new(n_join_all.outputs["Geometry"], n_shade.inputs["Geometry"])
    
    links.new(n_shade.outputs["Geometry"], n_out.inputs["Geometry"])
    return ng


# ==============================================================================
# OPERATORS: SETUP, BLUE ACTIVE MODE BUTTONS, BRIDGE HEIGHT & JUNCTIONS
# ==============================================================================
class ROAD_OT_CreateRoad(bpy.types.Operator):
    bl_idname = "road.create_mountain_road"
    bl_label = "Build / Upgrade AAA Road Network (V6.3)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        ng = create_road_node_group()
        mats = create_default_materials()
        
        active_obj = context.active_object
        terrain_target = bpy.data.objects.get("Landscape")
        
        if active_obj and active_obj.type == 'MESH' and not active_obj.name.endswith("_BakedMesh"):
            terrain_target = active_obj
            
        if not active_obj or active_obj.type != 'CURVE':
            bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, 2))
            obj = context.active_object
            obj.name = "Mountain_Road"
        else:
            obj = active_obj
            
        for sp in obj.data.splines:
            if sp.type == 'BEZIER':
                for pt in sp.bezier_points:
                    if pt.radius > 2.5:
                        pt.radius = 0.5
                    w_pos = obj.matrix_world @ pt.co
                    g_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                    new_z = max(pt.co.z, g_z + 0.50) if pt.radius > 1.50 else g_z
                    dz = new_z - pt.co.z
                    pt.co.z = new_z
                    pt.handle_left.z += dz
                    pt.handle_right.z += dz
            else:
                for pt in sp.points:
                    if pt.radius > 2.5:
                        pt.radius = 0.5
                        
        obj.modifiers.clear()
        mod = obj.modifiers.new(name="AAA Road Engine V6.3", type='NODES')
        mod.node_group = ng
        
        for item in ng.interface.items_tree:
            if item.in_out == 'INPUT':
                if item.name == "Terrain Target" and terrain_target:
                    mod[item.identifier] = terrain_target
                elif item.name == "Road Surface Material":
                    mod[item.identifier] = mats["Road_Asphalt_Mat"]
                elif item.name == "Embankment Dirt Material":
                    mod[item.identifier] = mats["Road_Embankment_Dirt_Mat"]
                elif item.name == "Bridge & Pillar Material":
                    mod[item.identifier] = mats["Road_Bridge_Concrete_Mat"]
                elif item.name == "Offroad Track Material":
                    mod[item.identifier] = mats["Road_Offroad_Track_Mat"]
                elif item.name == "Guardrail Material":
                    mod[item.identifier] = mats["Road_Guardrail_Steel_Mat"]
                    
        _last_spline_counts[obj.name] = len(obj.data.splines)
        obj.update_tag()
        self.report({'INFO'}, "V6.3 Applied! Multi-Bridge Spline Splitting Fixed (No Cross-Gap Wires or Pillars).")
        return {'FINISHED'}


class ROAD_OT_AdjustSelectedHeight(bpy.types.Operator):
    bl_idname = "road.adjust_selected_height"
    bl_label = "Adjust Selected Bridge Point Height"
    bl_options = {'REGISTER', 'UNDO'}
    delta_z: bpy.props.FloatProperty(default=1.0)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0
        for sp in obj.data.splines:
            if sp.type == 'BEZIER':
                for pt in sp.bezier_points:
                    if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                        w_pos = obj.matrix_world @ pt.co
                        min_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                        if pt.radius <= 1.50 and self.delta_z > 0.0:
                            pt.radius = 2.0
                            context.scene.road_active_mode = 1
                        if pt.radius > 1.50:
                            new_z = max(pt.co.z + self.delta_z, min_z + 0.45)
                            dz = new_z - pt.co.z
                            pt.co.z = new_z
                            pt.handle_left.z += dz
                            pt.handle_right.z += dz
                            count += 1
            else:
                for pt in sp.points:
                    if pt.select:
                        w_pos = obj.matrix_world @ Vector(pt.co[:3])
                        min_z = raycast_terrain_z_python(context, obj, w_pos, pt.co[2])
                        if pt.radius <= 1.50 and self.delta_z > 0.0:
                            pt.radius = 2.0
                            context.scene.road_active_mode = 1
                        if pt.radius > 1.50:
                            pt.co[2] = max(pt.co[2] + self.delta_z, min_z + 0.45)
                            count += 1
                            
        if count == 0:
            self.report({'WARNING'}, "Select a Bridge point in Edit Mode (Asphalt/Offroad stay glued to the terrain)!")
            return {'CANCELLED'}
            
        obj.update_tag()
        self.report({'INFO'}, f"Adjusted {count} Bridge point(s) (Clamped safely above terrain surface)!")
        return {'FINISHED'}


class ROAD_OT_GenerateCustomAssets(bpy.types.Operator):
    bl_idname = "road.generate_custom_assets"
    bl_label = "Generate Sample 2D Bridge, 3D Pillar & 3D Guardrail"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        road_obj = context.active_object
        if not road_obj or not road_obj.modifiers:
            self.report({'WARNING'}, "Select your Mountain_Road object first!")
            return {'CANCELLED'}
            
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        mats = create_default_materials()
        
        prof_name = "Custom_Bridge_2D_Profile"
        if prof_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[prof_name], do_unlink=True)
            
        curve_data = bpy.data.curves.new(name=prof_name, type='CURVE')
        curve_data.dimensions = '2D'
        sp = curve_data.splines.new('POLY')
        pts = [
            (-2.5, 0.0, 0.0, 1.0),
            (-2.5, 0.30, 0.0, 1.0),
            (-1.7, 0.40, 0.0, 1.0),
            (-1.2, 0.90, 0.0, 1.0),
            (1.2, 0.90, 0.0, 1.0),
            (1.7, 0.40, 0.0, 1.0),
            (2.5, 0.30, 0.0, 1.0),
            (2.5, 0.0, 0.0, 1.0),
        ]
        sp.points.add(len(pts) - 1)
        for i, co in enumerate(pts):
            sp.points[i].co = co
        sp.use_cyclic_u = True
        prof_obj = bpy.data.objects.new(prof_name, curve_data)
        context.collection.objects.link(prof_obj)
        prof_obj.location = (15, 0, 0)
            
        pil_name = "Custom_Pillar_3D_Mesh"
        if pil_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[pil_name], do_unlink=True)
            
        mesh_data = bpy.data.meshes.new(pil_name)
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co.x *= 1.1
            v.co.y *= 1.5
            v.co.z = (v.co.z - 0.5) * 4.0
            if v.co.z > -0.1:
                v.co.y *= 2.2
        bm.to_mesh(mesh_data)
        bm.free()
        mesh_data.materials.append(mats["Road_Bridge_Concrete_Mat"])
        pil_obj = bpy.data.objects.new(pil_name, mesh_data)
        context.collection.objects.link(pil_obj)
        pil_obj.location = (20, 0, 0)
        
        gr_name = "Custom_Guardrail_3D_Mesh"
        if gr_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[gr_name], do_unlink=True)
            
        gr_mesh = bpy.data.meshes.new(gr_name)
        bm_g = bmesh.new()
        res_post = bmesh.ops.create_cube(bm_g, size=1.0)
        for v in res_post["verts"]:
            v.co.x *= 0.14
            v.co.y *= 0.14
            v.co.z = (v.co.z + 0.5) * 0.85
        for z_rail in [0.52, 0.72]:
            res_rail = bmesh.ops.create_cube(bm_g, size=1.0)
            for v in res_rail["verts"]:
                v.co.x *= 3.05
                v.co.y = (v.co.y * 0.08) - 0.07
                v.co.z = (v.co.z * 0.13) + z_rail
        bm_g.to_mesh(gr_mesh)
        bm_g.free()
        gr_mesh.materials.append(mats["Road_Guardrail_Steel_Mat"])
        gr_obj = bpy.data.objects.new(gr_name, gr_mesh)
        context.collection.objects.link(gr_obj)
        gr_obj.location = (25, 0, 0)
            
        mod = road_obj.modifiers[0]
        ng = mod.node_group
        for item in ng.interface.items_tree:
            if item.in_out == 'INPUT':
                if item.name == "Use Custom 2D Bridge Profile":
                    mod[item.identifier] = True
                elif item.name == "Custom 2D Bridge Profile (Curve)":
                    mod[item.identifier] = prof_obj
                elif item.name == "Use Custom 3D Pillar Mesh":
                    mod[item.identifier] = True
                elif item.name == "Custom 3D Pillar Object (Mesh)":
                    mod[item.identifier] = pil_obj
                elif item.name == "Pillar Top Vertical Offset (m)":
                    mod[item.identifier] = -0.95
                elif item.name == "Use Custom 3D Guardrail Mesh":
                    mod[item.identifier] = True
                elif item.name == "Custom 3D Guardrail Object (Mesh)":
                    mod[item.identifier] = gr_obj
                    
        road_obj.update_tag()
        self.report({'INFO'}, "Generated & Linked 2D Bridge, 3D Pillar, AND 3D Guardrail Assets!")
        return {'FINISHED'}


class ROAD_OT_SetSegmentType(bpy.types.Operator):
    bl_idname = "road.set_segment_type"
    bl_label = "Select Active Road Mode / Convert Points"
    bl_options = {'REGISTER', 'UNDO'}
    seg_mode: bpy.props.IntProperty(default=0)

    def execute(self, context):
        context.scene.road_active_mode = self.seg_mode
        
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            return {'FINISHED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        rad_map = {0: 1.0, 1: 2.0, 2: 0.5}
        target_rad = rad_map.get(self.seg_mode, 1.0)
        
        count = 0
        for spline in obj.data.splines:
            if spline.type == 'BEZIER':
                for pt in spline.bezier_points:
                    if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                        w_pos = obj.matrix_world @ pt.co
                        g_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                        pt.radius = target_rad
                        new_z = max(pt.co.z + 3.5, g_z + 3.5) if self.seg_mode == 1 else g_z
                        dz = new_z - pt.co.z
                        pt.co.z = new_z
                        pt.handle_left.z += dz
                        pt.handle_right.z += dz
                        count += 1
            else:
                for pt in spline.points:
                    if pt.select:
                        pt.radius = target_rad
                        count += 1
                        
        obj.update_tag()
        names = {0: "Asphalt (Sticks to Ground)", 1: "Bridge (Elevated + Pillars)", 2: "Offroad Dirt (Sticks to Ground)"}
        self.report({'INFO'}, f"Active Mode: {names[self.seg_mode]} ({count} selected point(s) updated)!")
        return {'FINISHED'}


class ROAD_OT_ExtendSegment(bpy.types.Operator):
    bl_idname = "road.extend_segment"
    bl_label = "Extend New Road Segment"
    bl_options = {'REGISTER', 'UNDO'}
    seg_mode: bpy.props.IntProperty(default=0)

    def execute(self, context):
        context.scene.road_active_mode = self.seg_mode
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        rad_map = {0: 1.0, 1: 2.0, 2: 0.5}
        target_rad = rad_map.get(self.seg_mode, 1.0)
        
        sel_sp = None
        sel_idx = -1
        sel_pt = None
        
        for sp in obj.data.splines:
            if sp.type == 'BEZIER' and len(sp.bezier_points) >= 1:
                for idx, pt in enumerate(sp.bezier_points):
                    if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                        sel_sp = sp
                        sel_idx = idx
                        sel_pt = pt
                        break
            if sel_pt:
                break
                
        if not sel_pt:
            if len(obj.data.splines) > 0 and len(obj.data.splines[0].bezier_points) > 0:
                sel_sp = obj.data.splines[0]
                sel_idx = len(sel_sp.bezier_points) - 1
                sel_pt = sel_sp.bezier_points[sel_idx]
            else:
                self.report({'WARNING'}, "Select a point on your Road Curve in Edit Mode first!")
                return {'CANCELLED'}
                
        pts = sel_sp.bezier_points
        is_start = (sel_idx == 0 and len(pts) > 1)
        is_end = (sel_idx == len(pts) - 1)
        is_middle = (not is_start and not is_end)
        
        sel_co = sel_pt.co.copy()
        old_rad = sel_pt.radius
        
        if is_middle:
            t_vec = pts[sel_idx + 1].co - pts[sel_idx - 1].co
            tangent = Vector((t_vec.x, t_vec.y, 0.0)).normalized() if t_vec.length > 0.01 else Vector((1.0, 0.0, 0.0))
            out_dir = Vector((tangent.y, -tangent.x, 0.0)).normalized()
        elif is_start:
            t_vec = pts[0].co - pts[1].co
            out_dir = Vector((t_vec.x, t_vec.y, 0.0)).normalized() if t_vec.length > 0.01 else Vector((1.0, 0.0, 0.0))
        else:
            t_vec = (pts[-1].co - pts[-2].co) if len(pts) > 1 else (sel_pt.handle_right - sel_pt.co)
            out_dir = Vector((t_vec.x, t_vec.y, 0.0)).normalized() if t_vec.length > 0.01 else Vector((1.0, 0.0, 0.0))
            
        bpy.ops.curve.select_all(action='DESELECT')
        
        end_co = sel_co + out_dir * 15.0
        ground_z = raycast_terrain_z_python(context, obj, obj.matrix_world @ end_co, end_co.z)
        
        if self.seg_mode == 1:
            end_co.z = max(sel_co.z if old_rad > 1.50 else ground_z + 4.0, ground_z + 2.5)
        else:
            end_co.z = ground_z
            
        if is_end and not is_middle:
            if abs(old_rad - target_rad) > 0.1:
                # Shorten previous endpoint's right handle before adding transition point so it NEVER loops/kinks!
                prev_pt = pts[-1]
                prev_pt.handle_left_type = 'FREE'
                prev_pt.handle_right_type = 'FREE'
                prev_pt.handle_right = sel_co + out_dir * 0.25
                
                pts.add(2)
                trans_pt = pts[-2]
                new_pt = pts[-1]
                
                trans_co = sel_co + out_dir * 0.8
                trans_g_z = raycast_terrain_z_python(context, obj, obj.matrix_world @ trans_co, trans_co.z)
                trans_co.z = max(sel_co.z, trans_g_z + 0.6) if self.seg_mode == 1 else trans_g_z
                trans_pt.co = trans_co
                trans_pt.radius = target_rad
                trans_pt.handle_left_type = 'FREE'
                trans_pt.handle_right_type = 'FREE'
                trans_pt.handle_left = trans_co - out_dir * 0.25
                trans_pt.handle_right = trans_co + out_dir * 4.0
                
                new_pt.co = end_co
                new_pt.radius = target_rad
                new_pt.handle_left = end_co - out_dir * 4.5
                new_pt.handle_right = end_co + out_dir * 4.5
                new_pt.handle_left_type = 'AUTO'
                new_pt.handle_right_type = 'AUTO'
                new_pt.select_control_point = True
            else:
                pts.add(1)
                new_pt = pts[-1]
                new_pt.co = end_co
                new_pt.radius = target_rad
                new_pt.handle_left = end_co - out_dir * 4.5
                new_pt.handle_right = end_co + out_dir * 4.5
                new_pt.handle_left_type = 'AUTO'
                new_pt.handle_right_type = 'AUTO'
                new_pt.select_control_point = True
        else:
            new_sp = obj.data.splines.new('BEZIER')
            new_sp.bezier_points.add(1)
            p0, p1 = new_sp.bezier_points[0], new_sp.bezier_points[1]
            
            start_g_z = raycast_terrain_z_python(context, obj, obj.matrix_world @ sel_co, sel_co.z)
            p0_co = sel_co.copy()
            p0_co.z = max(sel_co.z, start_g_z + 2.0) if self.seg_mode == 1 else start_g_z
            
            p0.co = p0_co
            p0.radius = target_rad
            p0.handle_left = p0_co - out_dir * 2.0
            p0.handle_right = p0_co + out_dir * 4.5
            p0.handle_left_type = 'AUTO'
            p0.handle_right_type = 'AUTO'
            
            p1.co = end_co
            p1.radius = target_rad
            p1.handle_left = end_co - out_dir * 4.5
            p1.handle_right = end_co + out_dir * 4.5
            p1.handle_left_type = 'AUTO'
            p1.handle_right_type = 'AUTO'
            p1.select_control_point = True
            
        _last_spline_counts[obj.name] = len(obj.data.splines)
        obj.update_tag()
        names = {0: "Asphalt (Ground)", 1: "Bridge (Elevated)", 2: "Offroad (Ground)"}
        self.report({'INFO'}, f"Extended {names[self.seg_mode]}!")
        return {'FINISHED'}


class ROAD_OT_SnapPointsToTerrain(bpy.types.Operator):
    bl_idname = "road.snap_points_to_terrain"
    bl_label = "Snap Selected Points Down to Terrain Surface"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0
        for sp in obj.data.splines:
            if sp.type == 'BEZIER':
                for pt in sp.bezier_points:
                    if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                        w_pos = obj.matrix_world @ pt.co
                        new_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                        if pt.radius > 1.50:
                            new_z += 0.45
                        dz = new_z - pt.co.z
                        pt.co.z = new_z
                        pt.handle_left.z += dz
                        pt.handle_right.z += dz
                        count += 1
            else:
                for pt in sp.points:
                    if pt.select:
                        w_pos = obj.matrix_world @ Vector(pt.co[:3])
                        pt.co[2] = raycast_terrain_z_python(context, obj, w_pos, pt.co[2])
                        count += 1
                        
        obj.update_tag()
        self.report({'INFO'}, f"Snapped {count} point(s) cleanly onto the terrain surface!")
        return {'FINISHED'}


class ROAD_OT_SpawnJunction(bpy.types.Operator):
    bl_idname = "road.spawn_junction"
    bl_label = "Spawn T / Y / + Junction Branch"
    bl_options = {'REGISTER', 'UNDO'}
    junction_type: bpy.props.StringProperty(default='T')

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select a point on your Road Curve in Edit Mode first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        
        sel_co = None
        tangent = Vector((1.0, 0.0, 0.0))
        rad_map = {0: 1.0, 1: 2.0, 2: 0.5}
        sel_rad = rad_map.get(context.scene.road_active_mode, 1.0)
        
        for sp in obj.data.splines:
            if sp.type == 'BEZIER':
                pts = sp.bezier_points
                for i, pt in enumerate(pts):
                    if pt.select_control_point or pt.select_left_handle or pt.select_right_handle:
                        sel_co = pt.co.copy()
                        if i < len(pts) - 1:
                            t_vec = pts[i+1].co - pt.co
                        elif i > 0:
                            t_vec = pt.co - pts[i-1].co
                        else:
                            t_vec = pt.handle_right - pt.co
                        if t_vec.length > 0.01:
                            tangent = Vector((t_vec.x, t_vec.y, 0.0)).normalized()
                        break
            if sel_co:
                break
                
        if not sel_co:
            self.report({'WARNING'}, "Select a Curve Point in Edit Mode where you want the intersection!")
            return {'CANCELLED'}
            
        bpy.ops.curve.select_all(action='DESELECT')
        
        perp_left = Vector((-tangent.y, tangent.x, 0.0)).normalized()
        perp_right = -perp_left
        branch_len = 16.0
        
        def add_branch_spline(start_pos, dir_vec, radius_val):
            sp = obj.data.splines.new('BEZIER')
            sp.bezier_points.add(1)
            for idx, factor in enumerate([0.0, 1.0]):
                p = sp.bezier_points[idx]
                pos = start_pos + dir_vec * (branch_len * factor)
                g_z = raycast_terrain_z_python(context, obj, obj.matrix_world @ pos, pos.z)
                pos.z = max(pos.z, g_z + 0.5) if radius_val > 1.50 else g_z
                p.co = pos
                p.handle_left = pos - dir_vec * 4.0
                p.handle_right = pos + dir_vec * 4.0
                p.handle_left_type = 'AUTO'
                p.handle_right_type = 'AUTO'
                p.radius = radius_val
                if idx == 1:
                    p.select_control_point = True
                    
        if self.junction_type == 'T':
            add_branch_spline(sel_co, perp_right, sel_rad)
        elif self.junction_type == 'PLUS':
            add_branch_spline(sel_co, perp_left, sel_rad)
            add_branch_spline(sel_co, perp_right, sel_rad)
        elif self.junction_type == 'Y':
            dir1 = (tangent + perp_left * 0.75).normalized()
            dir2 = (tangent + perp_right * 0.75).normalized()
            add_branch_spline(sel_co, dir1, sel_rad)
            add_branch_spline(sel_co, dir2, sel_rad)
            
        _last_spline_counts[obj.name] = len(obj.data.splines)
        obj.update_tag()
        self.report({'INFO'}, f"Spawned clean {self.junction_type}-Intersection!")
        return {'FINISHED'}


class ROAD_OT_SnapBranchToRoad(bpy.types.Operator):
    bl_idname = "road.snap_branch"
    bl_label = "Connect / Snap Selected Roads"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        active_obj = context.active_object
        if not active_obj or active_obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve first!")
            return {'CANCELLED'}
            
        other_curves = [o for o in context.selected_objects if o.type == 'CURVE' and o != active_obj]
        if other_curves:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.join()
            
        bpy.ops.object.mode_set(mode='EDIT')
        splines = active_obj.data.splines
        if len(splines) < 2:
            self.report({'WARNING'}, "Need at least 2 road splines to connect!")
            return {'CANCELLED'}
            
        selected_by_spline = {}
        for sp_idx, sp in enumerate(splines):
            pts = sp.bezier_points if sp.type == 'BEZIER' else sp.points
            for pt_idx, p in enumerate(pts):
                sel = (p.select_control_point or p.select_left_handle or p.select_right_handle) if sp.type == 'BEZIER' else p.select
                if sel:
                    selected_by_spline.setdefault(sp_idx, []).append((sp, pt_idx, p))
                    
        if not selected_by_spline:
            self.report({'WARNING'}, "Select an endpoint on the branch road you want to connect!")
            return {'CANCELLED'}
            
        def snap_point_cleanly(sp, pt_idx, p, target_co):
            if sp.type == 'BEZIER':
                pts = sp.bezier_points
                p.handle_left_type = 'FREE'
                p.handle_right_type = 'FREE'
                p.co = target_co
                if pt_idx == 0 and len(pts) > 1:
                    neighbor_co = pts[1].co
                    vec = (neighbor_co - target_co) * 0.35
                    p.handle_right = target_co + vec
                    p.handle_left = target_co - vec * 0.05
                elif pt_idx == len(pts) - 1 and len(pts) > 1:
                    neighbor_co = pts[-2].co
                    vec = (neighbor_co - target_co) * 0.35
                    p.handle_left = target_co + vec
                    p.handle_right = target_co - vec * 0.05
            else:
                p.co = (target_co.x, target_co.y, target_co.z, 1.0)

        if len(selected_by_spline) >= 2:
            sp_indices = sorted(selected_by_spline.keys())
            target_sp_idx = sp_indices[0]
            _, _, target_pt = selected_by_spline[target_sp_idx][0]
            target_co = Vector(target_pt.co[:3])
            
            for branch_sp_idx in sp_indices[1:]:
                best_item = min(selected_by_spline[branch_sp_idx], key=lambda item: (Vector(item[2].co[:3]) - target_co).length)
                snap_point_cleanly(best_item[0], best_item[1], best_item[2], target_co)
                
            active_obj.update_tag()
            self.report({'INFO'}, "Connected the two selected roads cleanly!")
            return {'FINISHED'}

        branch_sp_idx = list(selected_by_spline.keys())[0]
        other_samples = []
        
        for sp_idx, sp in enumerate(splines):
            if sp_idx == branch_sp_idx:
                continue
            if sp.type == 'BEZIER':
                pts = sp.bezier_points
                for i in range(len(pts) - 1):
                    p0, p1 = pts[i], pts[i+1]
                    curve_samples = interpolate_bezier(p0.co, p0.handle_right, p1.handle_left, p1.co, 64)
                    other_samples.extend(curve_samples)
                if len(pts) == 1:
                    other_samples.append(pts[0].co.copy())
            else:
                pts = sp.points
                for i in range(len(pts) - 1):
                    c0 = Vector(pts[i].co[:3])
                    c1 = Vector(pts[i+1].co[:3])
                    for step in range(32):
                        other_samples.append(c0.lerp(c1, step / 31.0))
                        
        if not other_samples:
            self.report({'WARNING'}, "No other road spline found to snap to!")
            return {'CANCELLED'}
            
        for sp, pt_idx, p in selected_by_spline[branch_sp_idx]:
            co = Vector(p.co[:3])
            nearest_co = min(other_samples, key=lambda sample_co: (co - sample_co).length)
            snap_point_cleanly(sp, pt_idx, p, nearest_co)
            
        active_obj.update_tag()
        self.report({'INFO'}, "Snapped branch endpoint seamlessly onto target road!")
        return {'FINISHED'}


class ROAD_OT_SmoothHandles(bpy.types.Operator):
    bl_idname = "road.smooth_handles"
    bl_label = "Auto-Smooth Selected Curve Corners"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'CURVE':
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.curve.handle_type_set(type='AUTOMATIC')
            obj.update_tag()
            self.report({'INFO'}, "Smoothed Bezier handles automatically!")
        return {'FINISHED'}


class ROAD_OT_ClearAndDraw(bpy.types.Operator):
    bl_idname = "road.clear_and_draw"
    bl_label = "Clear & Draw Fresh Road"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'CURVE':
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.curve.select_all(action='SELECT')
            bpy.ops.curve.delete(type='VERT')
            _last_spline_counts[obj.name] = 0
            bpy.ops.wm.tool_set_by_id(name="builtin.draw")
            cps = context.scene.tool_settings.curve_paint_settings
            cps.depth_mode = 'SURFACE'
            cps.surface_offset = 0.25
            cps.use_offset_absolute = True
        return {'FINISHED'}


class ROAD_OT_ActivateDrawTool(bpy.types.Operator):
    bl_idname = "road.activate_draw_tool"
    bl_label = "Draw New Road Stroke (Uses Active Blue Mode)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'CURVE':
            bpy.ops.object.mode_set(mode='EDIT')
            _last_spline_counts[obj.name] = len(obj.data.splines)
            bpy.ops.wm.tool_set_by_id(name="builtin.draw")
            cps = context.scene.tool_settings.curve_paint_settings
            cps.depth_mode = 'SURFACE'
            cps.surface_offset = 0.25
            cps.use_offset_absolute = True
        return {'FINISHED'}


class ROAD_OT_SetPreset(bpy.types.Operator):
    bl_idname = "road.set_preset"
    bl_label = "Apply Mode to Entire Road"
    bl_options = {'REGISTER', 'UNDO'}
    preset_type: bpy.props.IntProperty(default=0)

    def execute(self, context):
        context.scene.road_active_mode = self.preset_type
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            return {'CANCELLED'}
            
        rad_map = {0: 1.0, 1: 2.0, 2: 0.5}
        target_rad = rad_map.get(self.preset_type, 1.0)
        
        for sp in obj.data.splines:
            for pt in sp.bezier_points:
                pt.radius = target_rad
                w_pos = obj.matrix_world @ pt.co
                g_z = raycast_terrain_z_python(context, obj, w_pos, pt.co.z)
                new_z = max(pt.co.z, g_z + 3.5) if self.preset_type == 1 else g_z
                dz = new_z - pt.co.z
                pt.co.z = new_z
                pt.handle_left.z += dz
                pt.handle_right.z += dz
            for pt in sp.points:
                pt.radius = target_rad
                
        obj.update_tag()
        names = {0: "Asphalt", 1: "Full Bridge", 2: "Offroad"}
        self.report({'INFO'}, f"Set all road points to {names[self.preset_type]}!")
        return {'FINISHED'}


class ROAD_OT_ConvertToMeshWithUV(bpy.types.Operator):
    bl_idname = "road.bake_for_mobile"
    bl_label = "Bake to Mesh + Activate UVMap (Safe)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "Select your Road object first!")
            return {'CANCELLED'}
            
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        new_mesh = bpy.data.meshes.new_from_object(eval_obj)
        
        baked_obj = bpy.data.objects.new(name=obj.name + "_BakedMesh", object_data=new_mesh)
        baked_obj.matrix_world = obj.matrix_world.copy()
        context.collection.objects.link(baked_obj)
        
        obj.hide_set(True)
        
        bpy.ops.object.select_all(action='DESELECT')
        baked_obj.select_set(True)
        context.view_layer.objects.active = baked_obj
        
        mesh = baked_obj.data
        if "UVMap" in mesh.attributes and "UVMap" not in mesh.uv_layers:
            attr = mesh.attributes["UVMap"]
            uv_data = [0.0] * (len(mesh.loops) * 2)
            attr.data.foreach_get("vector", uv_data)
            mesh.attributes.remove(attr)
            uv_layer = mesh.uv_layers.new(name="UVMap")
            uv_layer.data.foreach_set("uv", uv_data)
            mesh.uv_layers.active = uv_layer
            
        self.report({'INFO'}, f"Created '{baked_obj.name}' with active UVMap! Original curve hidden.")
        return {'FINISHED'}


# ==============================================================================
# UI PANEL: AAA STUDIO ROAD CREATOR V6.3 (ARGON PRO)
# ==============================================================================
class ROAD_PT_MainPanel(bpy.types.Panel):
    bl_label = "Mountain Road Creator V6.3"
    bl_idname = "ROAD_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Road Creator'

    def draw(self, context):
        layout = self.layout
        
        col = layout.column(align=True)
        col.scale_y = 1.35
        col.operator("road.create_mountain_road", icon='MOD_BUILD')
        row_draw = col.row(align=True)
        row_draw.operator("road.activate_draw_tool", text="Draw New Road", icon='LINE_DATA')
        row_draw.operator("road.clear_and_draw", text="Clear & Draw", icon='GREASEPENCIL')
        
        obj = context.active_object
        if obj and obj.modifiers and obj.modifiers[0].type == 'NODES':
            mod = obj.modifiers[0]
            ng = mod.node_group
            
            sel_pt_mode = get_selected_point_mode(obj)
            ui_mode = sel_pt_mode if sel_pt_mode is not None else getattr(context.scene, "road_active_mode", 0)
            mode_names = {0: "ASPHALT (Sticks to Terrain)", 1: "BRIDGE (Moves Up, Never Underground)", 2: "OFFROAD (Sticks to Terrain)"}
            
            layout.separator()
            box_seg = layout.box()
            box_seg.label(text=f"Active Mode: {mode_names.get(ui_mode, 'ASPHALT')}", icon='CHECKMARK')
            
            row_s = box_seg.row(align=True)
            row_s.scale_y = 1.35
            op_s0 = row_s.operator("road.set_segment_type", text="Asphalt", icon='RESTRICT_VIEW_OFF', depress=(ui_mode == 0))
            op_s0.seg_mode = 0
            op_s1 = row_s.operator("road.set_segment_type", text="Bridge+Pillars", icon='MOD_ARRAY', depress=(ui_mode == 1))
            op_s1.seg_mode = 1
            op_s2 = row_s.operator("road.set_segment_type", text="Offroad", icon='FORCE_TURBULENCE', depress=(ui_mode == 2))
            op_s2.seg_mode = 2
            
            box_seg.label(text="Extrude (Endpoint=Forward, Middle=90° Branch):", icon='ADD')
            row_ext = box_seg.row(align=True)
            row_ext.scale_y = 1.25
            op_e0 = row_ext.operator("road.extend_segment", text="+ Asphalt", depress=(ui_mode == 0))
            op_e0.seg_mode = 0
            op_e1 = row_ext.operator("road.extend_segment", text="+ Bridge", depress=(ui_mode == 1))
            op_e1.seg_mode = 1
            op_e2 = row_ext.operator("road.extend_segment", text="+ Offroad", depress=(ui_mode == 2))
            op_e2.seg_mode = 2
            
            layout.separator()
            box_h = layout.box()
            box_h.label(text="2. Bridge Height Control (Stops at Terrain):", icon='EMPTY_SINGLE_ARROW')
            col_h = box_h.column(align=True)
            col_h.scale_y = 1.25
            col_h.prop(context.scene, "road_selected_point_z", text="Selected Bridge Z Height (m)", slider=False)
            row_hb = box_h.row(align=True)
            for val, lbl in [(-5.0, "-5m"), (-1.0, "-1m"), (1.0, "+1m"), (5.0, "+5m")]:
                op_h = row_hb.operator("road.adjust_selected_height", text=lbl)
                op_h.delta_z = val
            box_h.operator("road.snap_points_to_terrain", text="Snap Bridge / Points Down to Terrain", icon='IMPORT')

            layout.separator()
            box_junc = layout.box()
            box_junc.label(text="3. Flared Intersections (No Overlap):", icon='PARTICLES')
            row_j = box_junc.row(align=True)
            op_jt = row_j.operator("road.spawn_junction", text="Spawn T")
            op_jt.junction_type = 'T'
            op_jy = row_j.operator("road.spawn_junction", text="Spawn Y")
            op_jy.junction_type = 'Y'
            op_jp = row_j.operator("road.spawn_junction", text="Spawn +")
            op_jp.junction_type = 'PLUS'
            
            col_j2 = box_junc.column(align=True)
            col_j2.scale_y = 1.25
            col_j2.operator("road.snap_branch", text="Connect / Snap Selected Roads", icon='SNAP_ON')
            col_j2.operator("road.smooth_handles", text="Smooth Selected Curve Handles", icon='IPO_BEZIER')

            layout.separator()
            box_cust = layout.box()
            box_cust.label(text="4. Custom 2D Bridge, 3D Pillar & 3D Guardrail:", icon='MESH_CYLINDER')
            box_cust.operator("road.generate_custom_assets", text="+ Generate 2D Bridge, 3D Pillar & 3D Guardrail", icon='ADD')

            layout.separator()
            box_mode = layout.box()
            box_mode.label(text="Reset Entire Road To:", icon='WORLD')
            row = box_mode.row(align=True)
            op1 = row.operator("road.set_preset", text="All Asphalt", depress=(ui_mode == 0))
            op1.preset_type = 0
            op2 = row.operator("road.set_preset", text="All Bridge", depress=(ui_mode == 1))
            op2.preset_type = 1
            op3 = row.operator("road.set_preset", text="All Offroad", depress=(ui_mode == 2))
            op3.preset_type = 2
            
            layout.separator()
            box2 = layout.box()
            box2.label(text="5. Civil Proportions, Guardrails & Materials:", icon='PREFERENCES')
            for item in ng.interface.items_tree:
                if item.in_out == 'INPUT' and item.name != "Geometry":
                    box2.prop(mod, f'["{item.identifier}"]', text=item.name)
                    
            layout.separator()
            col2 = layout.column()
            col2.scale_y = 1.4
            col2.operator("road.bake_for_mobile", icon='UV')


classes = (
    ROAD_OT_CreateRoad,
    ROAD_OT_AdjustSelectedHeight,
    ROAD_OT_GenerateCustomAssets,
    ROAD_OT_SetSegmentType,
    ROAD_OT_ExtendSegment,
    ROAD_OT_SnapPointsToTerrain,
    ROAD_OT_SpawnJunction,
    ROAD_OT_SnapBranchToRoad,
    ROAD_OT_SmoothHandles,
    ROAD_OT_ClearAndDraw,
    ROAD_OT_ActivateDrawTool,
    ROAD_OT_SetPreset,
    ROAD_OT_ConvertToMeshWithUV,
    ROAD_PT_MainPanel,
)

def register():
    for sub in list(bpy.types.Panel.__subclasses__()):
        if sub.__name__.startswith("ROAD_PT_") or getattr(sub, "bl_idname", "") == "ROAD_PT_main_panel":
            try:
                bpy.utils.unregister_class(sub)
            except Exception:
                pass
    for sub in list(bpy.types.Operator.__subclasses__()):
        if sub.__name__.startswith("ROAD_OT_"):
            try:
                bpy.utils.unregister_class(sub)
            except Exception:
                pass
                
    bpy.types.Scene.road_active_mode = bpy.props.IntProperty(name="Active Road Mode", default=0, min=0, max=2)
    bpy.types.Scene.road_selected_point_z = bpy.props.FloatProperty(
        name="Selected Bridge Z Height",
        description="Live Z height of selected Bridge point(s) (Clamped safely above terrain)",
        get=get_selected_points_z,
        set=set_selected_points_z,
        unit='LENGTH'
    )
    for cls in classes:
        bpy.utils.register_class(cls)
        
    if road_draw_and_clamp_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(road_draw_and_clamp_handler)

def unregister():
    if road_draw_and_clamp_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(road_draw_and_clamp_handler)
    for prop in ("road_selected_point_z", "road_active_mode"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

if __name__ == "__main__":
    register()