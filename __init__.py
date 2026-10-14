bl_info = {
    "name": "Mobile Game Mountain Road Creator V5.5.1 (AAA Custom Asset Edition)",
    "author": "Custom Game Dev Tool",
    "version": (5, 5, 1),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Road Creator",
    "description": "Smart Junction Wall Clearing, Custom 2D Bridge Profile, Custom 3D Pillars & Auto-UV Baker",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector

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
# HELPER: AUTO MATERIALS (ASPHALT, DIRT, CONCRETE, OFFROAD)
# ==============================================================================
def create_default_materials():
    mats = {}
    specs = [
        ("Road_Asphalt_Mat", (0.11, 0.11, 0.13, 1.0)),
        ("Road_Embankment_Dirt_Mat", (0.26, 0.17, 0.10, 1.0)),
        ("Road_Bridge_Concrete_Mat", (0.50, 0.51, 0.53, 1.0)),
        ("Road_Offroad_Track_Mat", (0.22, 0.14, 0.08, 1.0)),
    ]
    for name, col in specs:
        mat = bpy.data.materials.get(name)
        if not mat:
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            nt = mat.node_tree
            bsdf = nt.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = col
                bsdf.inputs["Roughness"].default_value = 0.85
                
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
# CORE GEOMETRY NODES ENGINE (V5.5.1 SMART JUNCTIONS + CUSTOM BRIDGE/PILLAR ASSETS)
# ==============================================================================
def create_road_node_group():
    group_name = "AAA_Road_Engine_v5_5"
    if group_name in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[group_name])
        
    ng = bpy.data.node_groups.new(group_name, 'GeometryNodeTree')
    
    # --- INTERFACE SOCKETS ---
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    
    ng.interface.new_socket("Terrain Target", in_out='INPUT', socket_type='NodeSocketObject')
    
    s_mode = ng.interface.new_socket("Default Mode (0:Asphalt, 1:Bridge, 2:Offroad)", in_out='INPUT', socket_type='NodeSocketInt')
    s_mode.default_value = 0
    s_mode.min_value = 0
    s_mode.max_value = 2
    
    s_width = ng.interface.new_socket("Road Width", in_out='INPUT', socket_type='NodeSocketFloat')
    s_width.default_value = 5.0
    s_width.min_value = 1.0
    
    s_spread = ng.interface.new_socket("Embankment Slope Spread", in_out='INPUT', socket_type='NodeSocketFloat')
    s_spread.default_value = 3.0
    s_spread.min_value = 0.0
    
    s_junc_rad = ng.interface.new_socket("Intersection Wall Clear Radius", in_out='INPUT', socket_type='NodeSocketFloat')
    s_junc_rad.default_value = 3.6
    s_junc_rad.min_value = 0.0
    
    s_height = ng.interface.new_socket("Road Height Above Terrain", in_out='INPUT', socket_type='NodeSocketFloat')
    s_height.default_value = 0.35
    s_height.min_value = 0.02
    
    s_res = ng.interface.new_socket("Segment Length (Poly Resolution)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_res.default_value = 1.0
    s_res.min_value = 0.25
    
    s_smooth = ng.interface.new_socket("Curve & Slope Smoothness", in_out='INPUT', socket_type='NodeSocketInt')
    s_smooth.default_value = 4
    s_smooth.min_value = 0
    s_smooth.max_value = 30
    
    s_uv_scale = ng.interface.new_socket("UV Texture Tiling Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s_uv_scale.default_value = 0.20
    s_uv_scale.min_value = 0.01

    # Bridge, Custom 2D Profile & Custom 3D Pillar Controls
    s_pillars = ng.interface.new_socket("Enable Bridge Pillars", in_out='INPUT', socket_type='NodeSocketBool')
    s_pillars.default_value = True
    
    s_auto_br = ng.interface.new_socket("Auto-Bridge When Lifted Above (m)", in_out='INPUT', socket_type='NodeSocketFloat')
    s_auto_br.default_value = 2.5
    s_auto_br.min_value = 0.5
    
    s_p_dist = ng.interface.new_socket("Pillar Spacing Distance", in_out='INPUT', socket_type='NodeSocketFloat')
    s_p_dist.default_value = 8.0
    s_p_dist.min_value = 2.0
    
    s_p_rad = ng.interface.new_socket("Pillar Thickness / Scale", in_out='INPUT', socket_type='NodeSocketFloat')
    s_p_rad.default_value = 0.65
    s_p_rad.min_value = 0.1
    
    s_wall_h = ng.interface.new_socket("Bridge Side Barrier Height", in_out='INPUT', socket_type='NodeSocketFloat')
    s_wall_h.default_value = 0.60
    s_wall_h.min_value = 0.0
    
    # NEW: Custom 2D Bridge Profile & Custom 3D Pillar Object Inputs!
    s_use_cust_br = ng.interface.new_socket("Use Custom 2D Bridge Profile", in_out='INPUT', socket_type='NodeSocketBool')
    s_use_cust_br.default_value = False
    ng.interface.new_socket("Custom 2D Bridge Profile (Curve)", in_out='INPUT', socket_type='NodeSocketObject')
    
    s_use_cust_pil = ng.interface.new_socket("Use Custom 3D Pillar Mesh", in_out='INPUT', socket_type='NodeSocketBool')
    s_use_cust_pil.default_value = False
    ng.interface.new_socket("Custom 3D Pillar Object (Mesh)", in_out='INPUT', socket_type='NodeSocketObject')

    # Offroad Controls
    s_off_noise = ng.interface.new_socket("Offroad Mud/Rock Bumpiness", in_out='INPUT', socket_type='NodeSocketFloat')
    s_off_noise.default_value = 0.35
    s_off_noise.min_value = 0.0
    
    s_off_crown = ng.interface.new_socket("Offroad Center Arch / Rut Depth", in_out='INPUT', socket_type='NodeSocketFloat')
    s_off_crown.default_value = -0.20
    s_off_crown.min_value = -1.5
    s_off_crown.max_value = 1.5

    # Materials
    ng.interface.new_socket("Road Surface Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Embankment Dirt Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Bridge & Pillar Material", in_out='INPUT', socket_type='NodeSocketMaterial')
    ng.interface.new_socket("Offroad Track Material", in_out='INPUT', socket_type='NodeSocketMaterial')

    nodes = ng.nodes
    links = ng.links
    n_in = nodes.new('NodeGroupInput')
    n_out = nodes.new('NodeGroupOutput')
    
    # ==========================================================================
    # STEP 1: RESAMPLE CURVE & DECODE PER-POINT SEGMENT TYPE
    # ==========================================================================
    n_resample = nodes.new('GeometryNodeResampleCurve')
    n_resample.mode = 'LENGTH'
    links.new(n_in.outputs["Geometry"], n_resample.inputs["Curve"])
    links.new(n_in.outputs["Segment Length (Poly Resolution)"], n_resample.inputs["Length"])
    
    n_obj = nodes.new('GeometryNodeObjectInfo')
    n_obj.transform_space = 'RELATIVE'
    links.new(n_in.outputs["Terrain Target"], n_obj.inputs["Object"])
    
    n_ray_center = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    
    n_c_pos = nodes.new('GeometryNodeInputPosition')
    n_sep_c = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_c_pos.outputs["Position"], n_sep_c.inputs["Vector"])
    n_sep_chit = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_center.outputs["Hit Position"], n_sep_chit.inputs["Vector"])
    
    n_lift_diff = nodes.new('ShaderNodeMath')
    n_lift_diff.operation = 'SUBTRACT'
    links.new(n_sep_c.outputs["Z"], n_lift_diff.inputs[0])
    links.new(n_sep_chit.outputs["Z"], n_lift_diff.inputs[1])
    
    n_is_lifted = nodes.new('FunctionNodeCompare')
    n_is_lifted.data_type = 'FLOAT'
    n_is_lifted.operation = 'GREATER_THAN'
    links.new(n_lift_diff.outputs["Value"], n_is_lifted.inputs[0])
    links.new(n_in.outputs["Auto-Bridge When Lifted Above (m)"], n_is_lifted.inputs[1])
    
    n_rad_in = nodes.new('GeometryNodeInputRadius')
    
    n_rad_gt_16 = nodes.new('FunctionNodeCompare')
    n_rad_gt_16.data_type = 'FLOAT'
    n_rad_gt_16.operation = 'GREATER_THAN'
    n_rad_gt_16.inputs[1].default_value = 1.6
    links.new(n_rad_in.outputs["Radius"], n_rad_gt_16.inputs[0])
    
    n_rad_lt_24 = nodes.new('FunctionNodeCompare')
    n_rad_lt_24.data_type = 'FLOAT'
    n_rad_lt_24.operation = 'LESS_THAN'
    n_rad_lt_24.inputs[1].default_value = 2.4
    links.new(n_rad_in.outputs["Radius"], n_rad_lt_24.inputs[0])
    
    n_rad_is_bridge = nodes.new('FunctionNodeBooleanMath')
    n_rad_is_bridge.operation = 'AND'
    links.new(n_rad_gt_16.outputs["Result"], n_rad_is_bridge.inputs[0])
    links.new(n_rad_lt_24.outputs["Result"], n_rad_is_bridge.inputs[1])
    
    n_rad_is_offroad = nodes.new('FunctionNodeCompare')
    n_rad_is_offroad.data_type = 'FLOAT'
    n_rad_is_offroad.operation = 'GREATER_THAN'
    n_rad_is_offroad.inputs[1].default_value = 2.5
    links.new(n_rad_in.outputs["Radius"], n_rad_is_offroad.inputs[0])
    
    n_glob_bridge = nodes.new('FunctionNodeCompare')
    n_glob_bridge.data_type = 'INT'
    n_glob_bridge.operation = 'EQUAL'
    n_glob_bridge.inputs[3].default_value = 1
    links.new(n_in.outputs["Default Mode (0:Asphalt, 1:Bridge, 2:Offroad)"], n_glob_bridge.inputs[2])
    
    n_glob_offroad = nodes.new('FunctionNodeCompare')
    n_glob_offroad.data_type = 'INT'
    n_glob_offroad.operation = 'EQUAL'
    n_glob_offroad.inputs[3].default_value = 2
    links.new(n_in.outputs["Default Mode (0:Asphalt, 1:Bridge, 2:Offroad)"], n_glob_offroad.inputs[2])
    
    n_br_or1 = nodes.new('FunctionNodeBooleanMath')
    n_br_or1.operation = 'OR'
    links.new(n_rad_is_bridge.outputs["Boolean"], n_br_or1.inputs[0])
    links.new(n_glob_bridge.outputs["Result"], n_br_or1.inputs[1])
    
    n_final_bridge = nodes.new('FunctionNodeBooleanMath')
    n_final_bridge.operation = 'OR'
    links.new(n_br_or1.outputs["Boolean"], n_final_bridge.inputs[0])
    links.new(n_is_lifted.outputs["Result"], n_final_bridge.inputs[1])
    
    n_off_or = nodes.new('FunctionNodeBooleanMath')
    n_off_or.operation = 'OR'
    links.new(n_rad_is_offroad.outputs["Result"], n_off_or.inputs[0])
    links.new(n_glob_offroad.outputs["Result"], n_off_or.inputs[1])
    
    n_not_br = nodes.new('FunctionNodeBooleanMath')
    n_not_br.operation = 'NOT'
    links.new(n_final_bridge.outputs["Boolean"], n_not_br.inputs[0])
    
    n_final_offroad = nodes.new('FunctionNodeBooleanMath')
    n_final_offroad.operation = 'AND'
    links.new(n_off_or.outputs["Boolean"], n_final_offroad.inputs[0])
    links.new(n_not_br.outputs["Boolean"], n_final_offroad.inputs[1])
    
    n_store_br = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_br.data_type = 'BOOLEAN'
    n_store_br.domain = 'POINT'
    n_store_br.inputs["Name"].default_value = "is_bridge"
    links.new(n_resample.outputs["Curve"], n_store_br.inputs["Geometry"])
    links.new(n_final_bridge.outputs["Boolean"], n_store_br.inputs["Value"])
    
    n_store_off = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_off.data_type = 'BOOLEAN'
    n_store_off.domain = 'POINT'
    n_store_off.inputs["Name"].default_value = "is_offroad"
    links.new(n_store_br.outputs["Geometry"], n_store_off.inputs["Geometry"])
    links.new(n_final_offroad.outputs["Boolean"], n_store_off.inputs["Value"])
    
    # Store Spline Index for tiny Z-bias at intersections so overlapping roads never Z-fight
    n_dom_idx = nodes.new('GeometryNodeInputIndex')
    n_store_sp_idx = nodes.new('GeometryNodeStoreNamedAttribute')
    n_store_sp_idx.data_type = 'INT'
    n_store_sp_idx.domain = 'CURVE'
    n_store_sp_idx.inputs["Name"].default_value = "sp_idx"
    links.new(n_store_off.outputs["Geometry"], n_store_sp_idx.inputs["Geometry"])
    links.new(n_dom_idx.outputs["Index"], n_store_sp_idx.inputs["Value"])
    
    n_rad_reset = nodes.new('GeometryNodeSetCurveRadius')
    n_rad_reset.inputs["Radius"].default_value = 1.0
    links.new(n_store_sp_idx.outputs["Geometry"], n_rad_reset.inputs["Curve"])
    
    n_tilt_reset = nodes.new('GeometryNodeSetCurveTilt')
    n_tilt_reset.inputs["Tilt"].default_value = 0.0
    links.new(n_rad_reset.outputs["Curve"], n_tilt_reset.inputs["Curve"])
    
    n_norm_z = nodes.new('GeometryNodeSetCurveNormal')
    n_norm_z.mode = 'Z_UP'
    links.new(n_tilt_reset.outputs["Curve"], n_norm_z.inputs["Curve"])

    # ==========================================================================
    # STEP 2: SNAP CURVE TO TERRAIN & SMOOTH (WHILE PINNING JUNCTION ENDPOINTS!)
    # ==========================================================================
    n_snap_sel = nodes.new('FunctionNodeBooleanMath')
    n_snap_sel.operation = 'AND'
    links.new(n_ray_center.outputs["Is Hit"], n_snap_sel.inputs[0])
    links.new(n_not_br.outputs["Boolean"], n_snap_sel.inputs[1])
    
    n_h_vec = nodes.new('ShaderNodeCombineXYZ')
    links.new(n_in.outputs["Road Height Above Terrain"], n_h_vec.inputs["Z"])
    
    n_hit_plus_h = nodes.new('ShaderNodeVectorMath')
    n_hit_plus_h.operation = 'ADD'
    links.new(n_ray_center.outputs["Hit Position"], n_hit_plus_h.inputs[0])
    links.new(n_h_vec.outputs["Vector"], n_hit_plus_h.inputs[1])
    
    n_set_c_pos = nodes.new('GeometryNodeSetPosition')
    links.new(n_norm_z.outputs["Curve"], n_set_c_pos.inputs["Geometry"])
    links.new(n_snap_sel.outputs["Boolean"], n_set_c_pos.inputs["Selection"])
    links.new(n_hit_plus_h.outputs["Vector"], n_set_c_pos.inputs["Position"])
    
    # Do NOT blur/pull the first/last endpoint of branches so T/Y/+ intersections stay 100% locked!
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
    
    n_smooth_c = nodes.new('GeometryNodeSetPosition')
    links.new(n_set_c_pos.outputs["Geometry"], n_smooth_c.inputs["Geometry"])
    links.new(n_not_end.outputs["Boolean"], n_smooth_c.inputs["Selection"])
    links.new(n_blur.outputs["Value"], n_smooth_c.inputs["Position"])
    
    n_norm_z2 = nodes.new('GeometryNodeSetCurveNormal')
    n_norm_z2.mode = 'Z_UP'
    links.new(n_smooth_c.outputs["Geometry"], n_norm_z2.inputs["Curve"])
    
    # Store "uv_v" along curve length
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
    # STEP 2B: BUILD INTERSECTION CLEARING POINT CLOUD
    # Collects all branch endpoints on splines >= 1 so walls/skirts auto-clear at junctions!
    # ==========================================================================
    n_read_sp_idx_c = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_sp_idx_c.data_type = 'INT'
    n_read_sp_idx_c.inputs["Name"].default_value = "sp_idx"
    
    n_is_branch_sp = nodes.new('FunctionNodeCompare')
    n_is_branch_sp.data_type = 'INT'
    n_is_branch_sp.operation = 'GREATER_THAN'
    n_is_branch_sp.inputs[3].default_value = 0
    links.new(n_read_sp_idx_c.outputs["Attribute"], n_is_branch_sp.inputs[2])
    
    n_junc_pt_sel = nodes.new('FunctionNodeBooleanMath')
    n_junc_pt_sel.operation = 'AND'
    links.new(n_end_sel.outputs["Selection"], n_junc_pt_sel.inputs[0])
    links.new(n_is_branch_sp.outputs["Result"], n_junc_pt_sel.inputs[1])
    
    n_junc_pts = nodes.new('GeometryNodeCurveToPoints')
    n_junc_pts.mode = 'EVALUATED'
    links.new(n_norm_z2.outputs["Curve"], n_junc_pts.inputs["Curve"])
    
    n_not_junc_pt = nodes.new('FunctionNodeBooleanMath')
    n_not_junc_pt.operation = 'NOT'
    links.new(n_junc_pt_sel.outputs["Boolean"], n_not_junc_pt.inputs[0])
    
    n_del_non_junc = nodes.new('GeometryNodeDeleteGeometry')
    n_del_non_junc.domain = 'POINT'
    links.new(n_junc_pts.outputs["Points"], n_del_non_junc.inputs["Geometry"])
    links.new(n_not_junc_pt.outputs["Boolean"], n_del_non_junc.inputs["Selection"])
    
    # Add dummy fallback point at (0, 0, -99999) so GeometryNodeProximity NEVER warns when only 1 spline exists!
    n_dummy_pt = nodes.new('GeometryNodeMeshLine')
    n_dummy_pt.inputs["Count"].default_value = 1
    n_dummy_pt.inputs["Start Location"].default_value = (0.0, 0.0, -99999.0)
    n_dummy_c2p = nodes.new('GeometryNodeMeshToPoints')
    links.new(n_dummy_pt.outputs["Mesh"], n_dummy_c2p.inputs["Mesh"])
    
    n_join_junc_cloud = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_del_non_junc.outputs["Geometry"], n_join_junc_cloud.inputs["Geometry"])
    links.new(n_dummy_c2p.outputs["Points"], n_join_junc_cloud.inputs["Geometry"])

    # ==========================================================================
    # STEP 3: BUILD TRUE 9-POINT SYMMETRIC CROSS-SECTION PROFILE
    # ==========================================================================
    n_half_w = nodes.new('ShaderNodeMath')
    n_half_w.operation = 'MULTIPLY'
    n_half_w.inputs[1].default_value = 0.5
    links.new(n_in.outputs["Road Width"], n_half_w.inputs[0])
    
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
    links.new(n_in.outputs["Embankment Slope Spread"], n_outer_dist.inputs[1])
    
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
    # STEP 5: VERTEX ELEVATION + SMART INTERSECTION WALL/SKIRT CLEARING
    # ==========================================================================
    n_ray_mesh = create_sky_raycast(nodes, links, n_obj.outputs["Geometry"])
    
    n_m_pos = nodes.new('GeometryNodeInputPosition')
    n_sep_m = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_m_pos.outputs["Position"], n_sep_m.inputs["Vector"])
    
    n_sep_mhit = nodes.new('ShaderNodeSeparateXYZ')
    links.new(n_ray_mesh.outputs["Hit Position"], n_sep_mhit.inputs["Vector"])
    
    n_ground_plus_h = nodes.new('ShaderNodeMath')
    n_ground_plus_h.operation = 'ADD'
    links.new(n_sep_mhit.outputs["Z"], n_ground_plus_h.inputs[0])
    links.new(n_in.outputs["Road Height Above Terrain"], n_ground_plus_h.inputs[1])
    
    n_asphalt_z = nodes.new('ShaderNodeMath')
    n_asphalt_z.operation = 'MAXIMUM'
    links.new(n_sep_m.outputs["Z"], n_asphalt_z.inputs[0])
    links.new(n_ground_plus_h.outputs["Value"], n_asphalt_z.inputs[1])
    
    # Offroad displacement
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
    
    n_offroad_z = nodes.new('ShaderNodeMath')
    n_offroad_z.operation = 'ADD'
    links.new(n_ground_plus_h.outputs["Value"], n_offroad_z.inputs[0])
    links.new(n_off_disp.outputs["Value"], n_offroad_z.inputs[1])
    
    # Read attributes on Mesh
    n_read_br_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_m.data_type = 'BOOLEAN'
    n_read_br_m.inputs["Name"].default_value = "is_bridge"
    
    n_read_off_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_off_m.data_type = 'BOOLEAN'
    n_read_off_m.inputs["Name"].default_value = "is_offroad"
    
    n_read_skirt_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_skirt_m.data_type = 'BOOLEAN'
    n_read_skirt_m.inputs["Name"].default_value = "is_skirt"
    
    n_read_sp_m = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_sp_m.data_type = 'INT'
    n_read_sp_m.inputs["Name"].default_value = "sp_idx"
    
    # Tiny Z-bias (sp_idx * 0.003m) so intersecting asphalt surfaces never Z-fight!
    n_z_bias = nodes.new('ShaderNodeMath')
    n_z_bias.operation = 'MULTIPLY'
    n_z_bias.inputs[1].default_value = 0.003
    links.new(n_read_sp_m.outputs["Attribute"], n_z_bias.inputs[0])
    
    n_sw_surf_z = nodes.new('GeometryNodeSwitch')
    n_sw_surf_z.input_type = 'FLOAT'
    links.new(n_read_off_m.outputs["Attribute"], n_sw_surf_z.inputs["Switch"])
    links.new(n_asphalt_z.outputs["Value"], n_sw_surf_z.inputs["False"])
    links.new(n_offroad_z.outputs["Value"], n_sw_surf_z.inputs["True"])
    
    n_sw_bridge_surf_z = nodes.new('GeometryNodeSwitch')
    n_sw_bridge_surf_z.input_type = 'FLOAT'
    links.new(n_read_br_m.outputs["Attribute"], n_sw_bridge_surf_z.inputs["Switch"])
    links.new(n_sw_surf_z.outputs["Output"], n_sw_bridge_surf_z.inputs["False"])
    links.new(n_sep_m.outputs["Z"], n_sw_bridge_surf_z.inputs["True"])
    
    n_surf_z_biased = nodes.new('ShaderNodeMath')
    n_surf_z_biased.operation = 'ADD'
    links.new(n_sw_bridge_surf_z.outputs["Output"], n_surf_z_biased.inputs[0])
    links.new(n_z_bias.outputs["Value"], n_surf_z_biased.inputs[1])
    
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
    n_eff_wall_h.inputs["True"].default_value = 0.0 # Clear wall inside junction!
    links.new(n_in_junc.outputs["Result"], n_eff_wall_h.inputs["Switch"])
    links.new(n_in.outputs["Bridge Side Barrier Height"], n_eff_wall_h.inputs["False"])
    
    n_skirt_ground_z = nodes.new('ShaderNodeMath')
    n_skirt_ground_z.operation = 'SUBTRACT'
    n_skirt_ground_z.inputs[1].default_value = 0.45
    links.new(n_sep_mhit.outputs["Z"], n_skirt_ground_z.inputs[0])
    
    n_skirt_junc_z = nodes.new('ShaderNodeMath')
    n_skirt_junc_z.operation = 'SUBTRACT'
    n_skirt_junc_z.inputs[1].default_value = 0.15
    links.new(n_sep_m.outputs["Z"], n_skirt_junc_z.inputs[0])
    
    n_sw_ground_junc_z = nodes.new('GeometryNodeSwitch')
    n_sw_ground_junc_z.input_type = 'FLOAT'
    links.new(n_in_junc.outputs["Result"], n_sw_ground_junc_z.inputs["Switch"])
    links.new(n_skirt_ground_z.outputs["Value"], n_sw_ground_junc_z.inputs["False"])
    links.new(n_skirt_junc_z.outputs["Value"], n_sw_ground_junc_z.inputs["True"])
        
    n_skirt_bridge_z = nodes.new('ShaderNodeMath')
    n_skirt_bridge_z.operation = 'ADD'
    links.new(n_sw_bridge_surf_z.outputs["Output"], n_skirt_bridge_z.inputs[0])
    links.new(n_eff_wall_h.outputs["Output"], n_skirt_bridge_z.inputs[1])
    
    n_sw_skirt_z = nodes.new('GeometryNodeSwitch')
    n_sw_skirt_z.input_type = 'FLOAT'
    links.new(n_read_br_m.outputs["Attribute"], n_sw_skirt_z.inputs["Switch"])
    links.new(n_sw_ground_junc_z.outputs["Output"], n_sw_skirt_z.inputs["False"])
    links.new(n_skirt_bridge_z.outputs["Value"], n_sw_skirt_z.inputs["True"])
    
    n_final_z = nodes.new('GeometryNodeSwitch')
    n_final_z.input_type = 'FLOAT'
    links.new(n_read_skirt_m.outputs["Attribute"], n_final_z.inputs["Switch"])
    links.new(n_surf_z_biased.outputs["Value"], n_final_z.inputs["False"])
    links.new(n_sw_skirt_z.outputs["Output"], n_final_z.inputs["True"])
    
    n_br_or_junc = nodes.new('FunctionNodeBooleanMath')
    n_br_or_junc.operation = 'OR'
    links.new(n_read_br_m.outputs["Attribute"], n_br_or_junc.inputs[0])
    links.new(n_in_junc.outputs["Result"], n_br_or_junc.inputs[1])
    
    n_pull_skirt_cond = nodes.new('FunctionNodeBooleanMath')
    n_pull_skirt_cond.operation = 'AND'
    links.new(n_read_skirt_m.outputs["Attribute"], n_pull_skirt_cond.inputs[0])
    links.new(n_br_or_junc.outputs["Boolean"], n_pull_skirt_cond.inputs[1])
    
    # === FIX 1: Convert curve to mesh to calculate proper proximity (stops origin snapping) ===
    n_prox_curve_mesh = nodes.new('GeometryNodeCurveToMesh')
    links.new(n_norm_z2.outputs["Curve"], n_prox_curve_mesh.inputs["Curve"])
    
    n_prox_curve = nodes.new('GeometryNodeProximity')
    n_prox_curve.target_element = 'EDGES'
    links.new(n_prox_curve_mesh.outputs["Mesh"], n_prox_curve.inputs["Target"])
    # =========================================================================================

    n_dir_from_c = nodes.new('ShaderNodeVectorMath')
    n_dir_from_c.operation = 'SUBTRACT'
    links.new(n_m_pos.outputs["Position"], n_dir_from_c.inputs[0])
    links.new(n_prox_curve.outputs["Position"], n_dir_from_c.inputs[1])
    
    n_norm_from_c = nodes.new('ShaderNodeVectorMath')
    n_norm_from_c.operation = 'NORMALIZE'
    links.new(n_dir_from_c.outputs["Vector"], n_norm_from_c.inputs[0])
    
    n_wall_outer_dist = nodes.new('ShaderNodeMath')
    n_wall_outer_dist.operation = 'ADD'
    n_wall_outer_dist.inputs[1].default_value = 0.25
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
    # STEP 6: ASSIGN 4 MATERIALS CLEANLY
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
    # STEP 6B: OPTIONAL CUSTOM 2D BRIDGE PROFILE DECK (SWEPT UNDER BRIDGE SECTIONS)
    # ==========================================================================
    n_cust_br_info = nodes.new('GeometryNodeObjectInfo')
    n_cust_br_info.transform_space = 'ORIGINAL'
    links.new(n_in.outputs["Custom 2D Bridge Profile (Curve)"], n_cust_br_info.inputs["Object"])
    
    # === FIX 2: Safely hide non-bridge profiles without breaking splines ===
    n_read_br_6b = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_6b.data_type = 'BOOLEAN'
    n_read_br_6b.inputs["Name"].default_value = "is_bridge"
    
    n_cust_br_rad = nodes.new('GeometryNodeSetCurveRadius')
    links.new(n_norm_z2.outputs["Curve"], n_cust_br_rad.inputs["Curve"])
    
    n_sw_br_rad = nodes.new('GeometryNodeSwitch')
    n_sw_br_rad.input_type = 'FLOAT'
    n_sw_br_rad.inputs["False"].default_value = 0.0
    n_sw_br_rad.inputs["True"].default_value = 1.0
    links.new(n_read_br_6b.outputs["Attribute"], n_sw_br_rad.inputs["Switch"])
    links.new(n_sw_br_rad.outputs["Output"], n_cust_br_rad.inputs["Radius"])

    n_c2m_cust_br = nodes.new('GeometryNodeCurveToMesh')
    n_c2m_cust_br.inputs["Fill Caps"].default_value = True
    links.new(n_cust_br_rad.outputs["Curve"], n_c2m_cust_br.inputs["Curve"])
    links.new(n_cust_br_info.outputs["Geometry"], n_c2m_cust_br.inputs["Profile Curve"])
    # ========================================================================
    
    n_mat_cust_br = nodes.new('GeometryNodeSetMaterial')
    links.new(n_c2m_cust_br.outputs["Mesh"], n_mat_cust_br.inputs["Geometry"])
    links.new(n_in.outputs["Bridge & Pillar Material"], n_mat_cust_br.inputs["Material"])
    
    n_sw_cust_br = nodes.new('GeometryNodeSwitch')
    n_sw_cust_br.input_type = 'GEOMETRY'
    links.new(n_in.outputs["Use Custom 2D Bridge Profile"], n_sw_cust_br.inputs["Switch"])
    links.new(n_mat_cust_br.outputs["Geometry"], n_sw_cust_br.inputs["True"])

    # ==========================================================================
    # STEP 7: BRIDGE SUPPORT PILLARS (PROCEDURAL CYLINDER OR CUSTOM 3D PILLAR MESH)
    # ==========================================================================
    n_res_pillars = nodes.new('GeometryNodeResampleCurve')
    n_res_pillars.mode = 'LENGTH'
    links.new(n_norm_z2.outputs["Curve"], n_res_pillars.inputs["Curve"])
    links.new(n_in.outputs["Pillar Spacing Distance"], n_res_pillars.inputs["Length"])
    
    n_samp_near = nodes.new('GeometryNodeSampleNearest')
    n_samp_near.domain = 'POINT'
    links.new(n_norm_z2.outputs["Curve"], n_samp_near.inputs["Geometry"])
    
    n_samp_br = nodes.new('GeometryNodeSampleIndex')
    n_samp_br.data_type = 'BOOLEAN'
    n_samp_br.domain = 'POINT'
    links.new(n_norm_z2.outputs["Curve"], n_samp_br.inputs["Geometry"])
    links.new(n_samp_near.outputs["Index"], n_samp_br.inputs["Index"])
    
    n_read_br_orig = nodes.new('GeometryNodeInputNamedAttribute')
    n_read_br_orig.data_type = 'BOOLEAN'
    n_read_br_orig.inputs["Name"].default_value = "is_bridge"
    links.new(n_read_br_orig.outputs["Attribute"], n_samp_br.inputs["Value"])
    
    n_prox_p_junc = nodes.new('GeometryNodeProximity')
    n_prox_p_junc.target_element = 'POINTS'
    links.new(n_join_junc_cloud.outputs["Geometry"], n_prox_p_junc.inputs["Target"])
    
    n_p_not_junc = nodes.new('FunctionNodeCompare')
    n_p_not_junc.data_type = 'FLOAT'
    n_p_not_junc.operation = 'GREATER_THAN'
    links.new(n_prox_p_junc.outputs["Distance"], n_p_not_junc.inputs[0])
    links.new(n_in.outputs["Intersection Wall Clear Radius"], n_p_not_junc.inputs[1])
    
    n_p_sel1 = nodes.new('FunctionNodeBooleanMath')
    n_p_sel1.operation = 'AND'
    links.new(n_in.outputs["Enable Bridge Pillars"], n_p_sel1.inputs[0])
    links.new(n_samp_br.outputs["Value"], n_p_sel1.inputs[1])
    
    n_p_sel = nodes.new('FunctionNodeBooleanMath')
    n_p_sel.operation = 'AND'
    links.new(n_p_sel1.outputs["Boolean"], n_p_sel.inputs[0])
    links.new(n_p_not_junc.outputs["Result"], n_p_sel.inputs[1])
    
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
    
    n_recess_p = nodes.new('GeometryNodeSetPosition')
    n_recess_p.inputs["Offset"].default_value = (0.0, 0.0, -0.18)
    links.new(n_res_pillars.outputs["Curve"], n_recess_p.inputs["Geometry"])
    
    n_c_tan = nodes.new('GeometryNodeInputTangent')
    n_align_rot = nodes.new('FunctionNodeAlignEulerToVector')
    n_align_rot.axis = 'X'
    n_align_rot.pivot_axis = 'Z'
    links.new(n_c_tan.outputs["Tangent"], n_align_rot.inputs["Vector"])
    
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
    links.new(n_align_rot.outputs["Rotation"], n_inst_p.inputs["Rotation"])
    links.new(n_p_scale.outputs["Vector"], n_inst_p.inputs["Scale"])
    
    n_realize_p = nodes.new('GeometryNodeRealizeInstances')
    links.new(n_inst_p.outputs["Instances"], n_realize_p.inputs["Geometry"])
    
    n_join_all = nodes.new('GeometryNodeJoinGeometry')
    links.new(n_mat_br_wall.outputs["Geometry"], n_join_all.inputs["Geometry"])
    links.new(n_sw_cust_br.outputs["Output"], n_join_all.inputs["Geometry"])
    links.new(n_realize_p.outputs["Geometry"], n_join_all.inputs["Geometry"])
    
    n_shade = nodes.new('GeometryNodeSetShadeSmooth')
    n_shade.inputs["Shade Smooth"].default_value = False
    links.new(n_join_all.outputs["Geometry"], n_shade.inputs["Geometry"])
    
    links.new(n_shade.outputs["Geometry"], n_out.inputs["Geometry"])
    return ng


# ==============================================================================
# OPERATORS: SETUP, CUSTOM ASSET GENERATOR & SMART JUNCTIONS
# ==============================================================================
class ROAD_OT_CreateRoad(bpy.types.Operator):
    bl_idname = "road.create_mountain_road"
    bl_label = "Build / Upgrade AAA Road Network (V5.5.1)"
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
            
        obj.modifiers.clear()
        mod = obj.modifiers.new(name="AAA Road Engine V5.5.1", type='NODES')
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
                    
        obj.update_tag()
        self.report({'INFO'}, "V5.5.1 Applied! Origin twisting fixed.")
        return {'FINISHED'}


class ROAD_OT_GenerateCustomAssets(bpy.types.Operator):
    """Generates a ready-to-edit 2D Bridge Girder Profile Curve and a 3D T-Hammerhead Concrete Pillar Mesh!"""
    bl_idname = "road.generate_custom_assets"
    bl_label = "Generate Sample 2D Bridge & 3D Pillar"
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
            prof_obj = bpy.data.objects[prof_name]
        else:
            curve_data = bpy.data.curves.new(name=prof_name, type='CURVE')
            curve_data.dimensions = '2D'
            sp = curve_data.splines.new('POLY')
            pts = [
                (-2.8, 0.0, 0.0, 1.0),
                (-2.8, -0.35, 0.0, 1.0),
                (-1.8, -0.45, 0.0, 1.0),
                (-1.2, -1.10, 0.0, 1.0),
                (1.2, -1.10, 0.0, 1.0),
                (1.8, -0.45, 0.0, 1.0),
                (2.8, -0.35, 0.0, 1.0),
                (2.8, 0.0, 0.0, 1.0),
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
            pil_obj = bpy.data.objects[pil_name]
        else:
            mesh_data = bpy.data.meshes.new(pil_name)
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            for v in bm.verts:
                v.co.x *= 1.1
                v.co.y *= 1.6
                v.co.z = (v.co.z - 0.5) * 4.0 
                if v.co.z > -0.1:
                    v.co.y *= 2.4
            bm.to_mesh(mesh_data)
            bm.free()
            mesh_data.materials.append(mats["Road_Bridge_Concrete_Mat"])
            pil_obj = bpy.data.objects.new(pil_name, mesh_data)
            context.collection.objects.link(pil_obj)
            pil_obj.location = (20, 0, 0)
            
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
                    
        road_obj.update_tag()
        self.report({'INFO'}, "Created & Linked 'Custom_Bridge_2D_Profile' & 'Custom_Pillar_3D_Mesh'! Edit them anytime.")
        return {'FINISHED'}


class ROAD_OT_SetSegmentType(bpy.types.Operator):
    bl_idname = "road.set_segment_type"
    bl_label = "Assign Segment Type to Selected Points"
    bl_options = {'REGISTER', 'UNDO'}
    seg_mode: bpy.props.IntProperty(default=0)

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        rad_map = {0: 1.0, 1: 2.0, 2: 3.0}
        target_rad = rad_map.get(self.seg_mode, 1.0)
        
        count = 0
        for spline in obj.data.splines:
            for pt in spline.bezier_points:
                if pt.select_control_point:
                    pt.radius = target_rad
                    if self.seg_mode == 1:
                        pt.co.z += 3.5
                        pt.handle_left.z += 3.5
                        pt.handle_right.z += 3.5
                    count += 1
            for pt in spline.points:
                if pt.select:
                    pt.radius = target_rad
                    if self.seg_mode == 1:
                        pt.co[2] += 3.5
                    count += 1
                    
        obj.update_tag()
        names = {0: "Asphalt Highway", 1: "Elevated Bridge (with Pillars)", 2: "Offroad Dirt Track"}
        self.report({'INFO'}, f"Set {count} point(s) to {names[self.seg_mode]}!")
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
        sel_rad = 1.0
        
        for sp in obj.data.splines:
            if sp.type == 'BEZIER':
                for i, pt in enumerate(sp.bezier_points):
                    if pt.select_control_point:
                        sel_co = pt.co.copy()
                        sel_rad = pt.radius
                        t_vec = (pt.handle_right - pt.co)
                        if t_vec.length > 0.01:
                            tangent = Vector((t_vec.x, t_vec.y, 0.0)).normalized()
                        break
            else:
                for i, pt in enumerate(sp.points):
                    if pt.select:
                        sel_co = Vector(pt.co[:3])
                        sel_rad = pt.radius
                        break
            if sel_co:
                break
                
        if not sel_co:
            self.report({'WARNING'}, "Select a Curve Point in Edit Mode where you want the intersection!")
            return {'CANCELLED'}
            
        bpy.ops.curve.select_all(action='DESELECT')
        
        perp_left = Vector((-tangent.y, tangent.x, 0.0)).normalized()
        perp_right = -perp_left
        branch_len = 14.0
        
        def add_branch_spline(start_pos, dir_vec, radius_val):
            sp = obj.data.splines.new('BEZIER')
            sp.bezier_points.add(2)
            for idx, factor in enumerate([0.0, 0.5, 1.0]):
                p = sp.bezier_points[idx]
                pos = start_pos + dir_vec * (branch_len * factor)
                p.co = pos
                p.handle_left_type = 'VECTOR' if idx == 0 else 'AUTO'
                p.handle_right_type = 'VECTOR' if idx == 0 else 'AUTO'
                p.radius = radius_val
                if idx == 2:
                    p.select_control_point = True
                    
        if self.junction_type == 'T':
            add_branch_spline(sel_co, perp_right, sel_rad)
        elif self.junction_type == 'PLUS':
            add_branch_spline(sel_co, perp_left, sel_rad)
            add_branch_spline(sel_co, perp_right, sel_rad)
        elif self.junction_type == 'Y':
            dir1 = (tangent + perp_left * 0.7).normalized()
            dir2 = (tangent + perp_right * 0.7).normalized()
            add_branch_spline(sel_co, dir1, sel_rad)
            add_branch_spline(sel_co, dir2, sel_rad)
            
        obj.update_tag()
        self.report({'INFO'}, f"Spawned clean {self.junction_type}-Intersection! Side walls cleared automatically.")
        return {'FINISHED'}


class ROAD_OT_SnapBranchToRoad(bpy.types.Operator):
    bl_idname = "road.snap_branch"
    bl_label = "Snap Selected Endpoint to Nearest Road"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'CURVE':
            self.report({'WARNING'}, "Select your Road Curve in Edit Mode first!")
            return {'CANCELLED'}
            
        bpy.ops.object.mode_set(mode='EDIT')
        splines = obj.data.splines
        if len(splines) < 2:
            self.report({'WARNING'}, "You need at least 2 road splines to snap a branch!")
            return {'CANCELLED'}
            
        selected_pts = []
        unselected_samples = []
        
        for sp in splines:
            pts = sp.bezier_points if sp.type == 'BEZIER' else sp.points
            for i, p in enumerate(pts):
                sel = p.select_control_point if sp.type == 'BEZIER' else p.select
                co = Vector(p.co[:3])
                rad = p.radius
                if sel:
                    selected_pts.append((sp, p))
                else:
                    unselected_samples.append((co, rad))
                    if i < len(pts) - 1:
                        next_co = Vector(pts[i+1].co[:3])
                        next_rad = pts[i+1].radius
                        for step in range(1, 15):
                            t = step / 15.0
                            unselected_samples.append((co.lerp(next_co, t), rad * (1 - t) + next_rad * t))
                            
        if not selected_pts or not unselected_samples:
            self.report({'WARNING'}, "Select only the endpoint of the branch road you want to connect!")
            return {'CANCELLED'}
            
        for sp, p in selected_pts:
            co = Vector(p.co[:3])
            nearest_co, nearest_rad = min(unselected_samples, key=lambda item: (co - item[0]).length)
            p.radius = nearest_rad 
            if sp.type == 'BEZIER':
                delta = nearest_co - p.co
                p.co = nearest_co
                p.handle_left += delta
                p.handle_right += delta
            else:
                p.co = (nearest_co.x, nearest_co.y, nearest_co.z, 1.0)
                
        obj.update_tag()
        self.report({'INFO'}, "Connected branch road seamlessly & cleared side walls at junction!")
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
            bpy.ops.wm.tool_set_by_id(name="builtin.draw")
            cps = context.scene.tool_settings.curve_paint_settings
            cps.depth_mode = 'SURFACE'
            cps.surface_offset = 0.25
            cps.use_offset_absolute = True
        return {'FINISHED'}


class ROAD_OT_SetPreset(bpy.types.Operator):
    bl_idname = "road.set_preset"
    bl_label = "Set Global Road Mode"
    preset_type: bpy.props.IntProperty(default=0)

    def execute(self, context):
        obj = context.active_object
        if not obj or not obj.modifiers:
            return {'CANCELLED'}
        mod = obj.modifiers[0]
        ng = mod.node_group
        
        for item in ng.interface.items_tree:
            if item.in_out == 'INPUT' and "Default Mode" in item.name:
                mod[item.identifier] = self.preset_type
        obj.update_tag()
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
# UI PANEL: AAA STUDIO ROAD CREATOR V5.5.1
# ==============================================================================
class ROAD_PT_MainPanel(bpy.types.Panel):
    bl_label = "AAA Road Creator V5.5.1"
    bl_idname = "ROAD_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Road Creator'

    def draw(self, context):
        layout = self.layout
        
        col = layout.column(align=True)
        col.scale_y = 1.35
        col.operator("road.create_mountain_road", icon='MOD_BUILD')
        col.operator("road.clear_and_draw", icon='GREASEPENCIL')
        
        obj = context.active_object
        if obj and obj.modifiers and obj.modifiers[0].type == 'NODES':
            mod = obj.modifiers[0]
            ng = mod.node_group
            
            layout.separator()
            box_seg = layout.box()
            box_seg.label(text="Mix Road Types (Select Points in Edit Mode):", icon='MATERIAL')
            row_s = box_seg.row(align=True)
            op_s0 = row_s.operator("road.set_segment_type", text="Asphalt", icon='RESTRICT_VIEW_OFF')
            op_s0.seg_mode = 0
            op_s1 = row_s.operator("road.set_segment_type", text="Bridge+Pillars", icon='MOD_ARRAY')
            op_s1.seg_mode = 1
            op_s2 = row_s.operator("road.set_segment_type", text="Offroad", icon='FORCE_TURBULENCE')
            op_s2.seg_mode = 2

            layout.separator()
            box_junc = layout.box()
            box_junc.label(text="Smart Intersections (Auto-Clears Side Walls):", icon='PARTICLES')
            row_j = box_junc.row(align=True)
            op_jt = row_j.operator("road.spawn_junction", text="Spawn T")
            op_jt.junction_type = 'T'
            op_jy = row_j.operator("road.spawn_junction", text="Spawn Y")
            op_jy.junction_type = 'Y'
            op_jp = row_j.operator("road.spawn_junction", text="Spawn +")
            op_jp.junction_type = 'PLUS'
            
            col_j2 = box_junc.column(align=True)
            col_j2.operator("road.snap_branch", text="Connect Branch Endpoint to Road", icon='SNAP_ON')
            col_j2.operator("road.smooth_handles", text="Smooth Selected Curve Handles", icon='IPO_BEZIER')

            layout.separator()
            box_cust = layout.box()
            box_cust.label(text="Custom 2D Bridge & 3D Pillar Assets:", icon='MESH_CYLINDER')
            box_cust.operator("road.generate_custom_assets", text="+ Generate Sample 2D Bridge & 3D Pillar", icon='ADD')

            layout.separator()
            box_mode = layout.box()
            box_mode.label(text="Global Default Mode:", icon='WORLD')
            row = box_mode.row(align=True)
            op1 = row.operator("road.set_preset", text="Asphalt")
            op1.preset_type = 0
            op2 = row.operator("road.set_preset", text="Full Bridge")
            op2.preset_type = 1
            op3 = row.operator("road.set_preset", text="Offroad")
            op3.preset_type = 2
            
            layout.separator()
            box2 = layout.box()
            box2.label(text="Parameters, Custom Objects & Materials:", icon='PREFERENCES')
            for item in ng.interface.items_tree:
                if item.in_out == 'INPUT' and item.name != "Geometry":
                    box2.prop(mod, f'["{item.identifier}"]', text=item.name)
                    
            layout.separator()
            col2 = layout.column()
            col2.scale_y = 1.4
            col2.operator("road.bake_for_mobile", icon='UV')


classes = (
    ROAD_OT_CreateRoad,
    ROAD_OT_GenerateCustomAssets,
    ROAD_OT_SetSegmentType,
    ROAD_OT_SpawnJunction,
    ROAD_OT_SnapBranchToRoad,
    ROAD_OT_SmoothHandles,
    ROAD_OT_ClearAndDraw,
    ROAD_OT_SetPreset,
    ROAD_OT_ConvertToMeshWithUV,
    ROAD_PT_MainPanel,
)

def register():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass

def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

if __name__ == "__main__":
    register()