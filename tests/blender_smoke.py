"""Run with Blender in background mode to validate operator registration and execution."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "randomize_value"


def load_extension():
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        REPOSITORY_ROOT / "__init__.py",
        submodule_search_locations=[str(REPOSITORY_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create the Randomize Value module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def vector_property(values):
    return tuple(values) + (0.0,) * (32 - len(values))


def context_targets(extension, context, description):
    return extension._matching_context_targets(
        context,
        description.root_mode,
        description.owner_path,
        description.owner_type,
        description.property_name,
        description.value_type,
        description.is_custom,
        description.match_name,
        description.match_type,
        description.source_data_name,
        description.source_data_library,
        description.match_direction,
    )


def button_context(pointer, property_name, **values):
    defaults = {
        "button_pointer": pointer,
        "button_prop": pointer.bl_rna.properties[property_name],
        "space_data": None,
        "object": None,
        "active_object": None,
        "selected_objects": [],
        "active_pose_bone": None,
        "active_bone": None,
        "selected_pose_bones": [],
        "selected_editable_bones": [],
        "selected_bones": [],
        "selected_editable_strips": [],
        "selected_strips": [],
        "selected_editable_fcurves": [],
        "selected_editable_keyframes": [],
        "selected_editable_actions": [],
        "selected_nla_strips": [],
        "selected_movieclip_tracks": [],
        "selected_assets": [],
        "selected_ids": [],
        "scene": bpy.context.scene,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def check_bone_targets(extension):
    armature = bpy.data.armatures.new("RandomizeValue_Armature")
    armature_object = bpy.data.objects.new("RandomizeValue_Armature", armature)
    bpy.context.scene.collection.objects.link(armature_object)
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    first_edit = armature.edit_bones.new("First")
    first_edit.tail = (0.0, 0.0, 1.0)
    second_edit = armature.edit_bones.new("Second")
    second_edit.head = (1.0, 0.0, 0.0)
    second_edit.tail = (1.0, 0.0, 1.0)

    edit_context = button_context(
        first_edit,
        "head",
        object=armature_object,
        active_object=armature_object,
        active_bone=first_edit,
        selected_editable_bones=[first_edit, second_edit],
    )
    description = extension._describe_button(edit_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_EDIT_BONE
    assert len(context_targets(extension, edit_context, description)) == 2

    bpy.ops.object.mode_set(mode="POSE")
    first_pose = armature_object.pose.bones["First"]
    second_pose = armature_object.pose.bones["Second"]
    pose_context = button_context(
        first_pose,
        "location",
        object=armature_object,
        active_object=armature_object,
        active_pose_bone=first_pose,
        active_bone=first_pose.bone,
        selected_pose_bones=[first_pose, second_pose],
    )
    description = extension._describe_button(pose_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_POSE_BONE
    assert len(context_targets(extension, pose_context, description)) == 2

    first_constraint = first_pose.constraints.new("COPY_LOCATION")
    second_constraint = second_pose.constraints.new("COPY_LOCATION")
    first_constraint.name = second_constraint.name = "Shared Constraint"
    constraint_context = button_context(
        first_constraint,
        "influence",
        object=armature_object,
        active_object=armature_object,
        active_pose_bone=first_pose,
        active_bone=first_pose.bone,
        selected_pose_bones=[first_pose, second_pose],
    )
    description = extension._describe_button(constraint_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_POSE_BONE
    assert description.owner_path == 'constraints["Shared Constraint"]'
    assert len(context_targets(extension, constraint_context, description)) == 2

    color_context = button_context(
        first_pose.color,
        "palette",
        object=armature_object,
        active_object=armature_object,
        active_pose_bone=first_pose,
        active_bone=first_pose.bone,
        selected_pose_bones=[first_pose, second_pose],
    )
    description = extension._describe_button(color_context)
    assert description is not None
    assert description.owner_path == "color"
    assert len(context_targets(extension, color_context, description)) == 2
    bpy.ops.object.mode_set(mode="OBJECT")


def check_animation_targets(extension):
    mesh = bpy.data.meshes.new("RandomizeValue_AnimationMesh")
    obj = bpy.data.objects.new("RandomizeValue_Animation", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.animation_data_create()
    action = bpy.data.actions.new("RandomizeValue_Action")
    obj.animation_data.action = action
    first_curve = action.fcurve_ensure_for_datablock(obj, "location", index=0)
    second_curve = action.fcurve_ensure_for_datablock(obj, "location", index=1)
    first_key = first_curve.keyframe_points.insert(1.0, 1.0)
    second_key = second_curve.keyframe_points.insert(1.0, 2.0)
    first_modifier = first_curve.modifiers.new("NOISE")
    second_modifier = second_curve.modifiers.new("NOISE")

    curve_context = button_context(
        first_curve,
        "extrapolation",
        selected_editable_fcurves=[first_curve, second_curve],
    )
    description = extension._describe_button(curve_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_FCURVE
    assert len(context_targets(extension, curve_context, description)) == 2

    modifier_context = button_context(
        first_modifier,
        "strength",
        selected_editable_fcurves=[first_curve, second_curve],
    )
    description = extension._describe_button(modifier_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_FCURVE_MODIFIER
    assert description.match_type == "NOISE"
    assert len(context_targets(extension, modifier_context, description)) == 2

    key_context = button_context(
        first_key,
        "interpolation",
        selected_editable_keyframes=[first_key, second_key],
    )
    description = extension._describe_button(key_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_KEYFRAME
    assert len(context_targets(extension, key_context, description)) == 2

    second_action = bpy.data.actions.new("RandomizeValue_ActionTwo")
    action_context = button_context(
        action,
        "use_cyclic",
        selected_editable_actions=[action, second_action],
    )
    description = extension._describe_button(action_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_ACTION
    assert len(context_targets(extension, action_context, description)) == 2

    track = obj.animation_data.nla_tracks.new()
    first_strip = track.strips.new("First", 1, action)
    second_strip = track.strips.new("Second", 100, action)
    nla_context = button_context(
        first_strip,
        "scale",
        selected_nla_strips=[first_strip, second_strip],
    )
    description = extension._describe_button(nla_context)
    assert description is not None
    assert description.root_mode == extension.ROOT_NLA_STRIP
    assert len(context_targets(extension, nla_context, description)) == 2


def check_strip_targets(extension):
    sequence_editor = bpy.context.scene.sequence_editor_create()
    first = sequence_editor.strips.new_effect(
        name="RandomizeValue_StripA",
        type="COLOR",
        channel=1,
        frame_start=1,
        length=20,
    )
    second = sequence_editor.strips.new_effect(
        name="RandomizeValue_StripB",
        type="TEXT",
        channel=2,
        frame_start=1,
        length=20,
    )
    context = button_context(
        first.transform,
        "offset_x",
        selected_editable_strips=[first, second],
        selected_strips=[first, second],
    )
    description = extension._describe_button(context)
    assert description is not None
    assert description.root_mode == extension.ROOT_STRIP
    assert description.owner_path == "transform"
    assert len(context_targets(extension, context, description)) == 2

    direct_context = button_context(
        first,
        "blend_alpha",
        selected_editable_strips=[first, second],
        selected_strips=[first, second],
    )
    description = extension._describe_button(direct_context)
    assert description is not None
    assert description.owner_type == ""
    assert len(context_targets(extension, direct_context, description)) == 2


def check_shape_key_targets(extension):
    mesh = bpy.data.meshes.new("RandomizeValue_ShapeMesh")
    obj = bpy.data.objects.new("RandomizeValue_Shape", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.shape_key_add(name="Basis")
    first = obj.shape_key_add(name="First")
    second = obj.shape_key_add(name="Second")
    ignored = obj.shape_key_add(name="Ignored")
    first.select = second.select = True
    ignored.select = False
    context = button_context(first, "value", object=obj, active_object=obj)
    description = extension._describe_button(context)
    assert description is not None
    assert description.root_mode == extension.ROOT_SHAPE_KEY
    targets = context_targets(extension, context, description)
    assert {target[0].name for target in targets} == {"First", "Second"}


def check_asset_metadata_targets(extension):
    first = bpy.data.materials.new("RandomizeValue_AssetA")
    second = bpy.data.materials.new("RandomizeValue_AssetB")
    first.asset_mark()
    second.asset_mark()
    context = button_context(
        first.asset_data,
        "active_tag",
        selected_assets=[
            SimpleNamespace(metadata=first.asset_data),
            SimpleNamespace(metadata=second.asset_data),
        ],
    )
    description = extension._describe_button(context)
    assert description is not None
    assert description.root_mode == extension.ROOT_ASSET_METADATA
    assert len(context_targets(extension, context, description)) == 2


def check_node_interface_targets(extension):
    node_group = bpy.data.node_groups.new(
        "RandomizeValue_InterfaceTree",
        "GeometryNodeTree",
    )
    source = node_group.interface.new_socket(
        name="Source",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    matching = node_group.interface.new_socket(
        name="Matching",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    different = node_group.interface.new_socket(
        name="Different",
        in_out="INPUT",
        socket_type="NodeSocketVector",
    )
    source.select = matching.select = different.select = True

    context = button_context(source, "default_value")
    description = extension._describe_button(context)
    assert description is not None
    assert description.root_mode == extension.ROOT_NODE_INTERFACE
    assert {target[0].name for target in context_targets(extension, context, description)} == {
        "Source",
        "Matching",
    }

    generic_context = button_context(source, "hide_value")
    description = extension._describe_button(generic_context)
    assert description is not None
    assert len(context_targets(extension, generic_context, description)) == 3


def check_outliner_object_targets(extension):
    first = bpy.data.objects.new("RandomizeValue_OutlinerA", None)
    second = bpy.data.objects.new("RandomizeValue_OutlinerB", None)
    bpy.context.scene.collection.objects.link(first)
    bpy.context.scene.collection.objects.link(second)
    context = button_context(
        first,
        "display_type",
        object=first,
        active_object=first,
        selected_ids=[first, second],
    )
    assert extension._selected_objects(context) == [first, second]


def check_node_tree_targets(extension, node_tree, node_type, other_node_type):
    node_tree.nodes.clear()
    source = node_tree.nodes.new(node_type)
    target = node_tree.nodes.new(node_type)
    other = node_tree.nodes.new(other_node_type)
    source.select = True
    target.select = True
    other.select = True

    source_socket = source.outputs[0]
    context = SimpleNamespace(
        button_pointer=source_socket,
        button_prop=source_socket.bl_rna.properties["default_value"],
        space_data=SimpleNamespace(edit_tree=node_tree, node_tree=node_tree),
        selected_nodes=[source, target, other],
        object=None,
        active_object=None,
        selected_objects=[],
    )
    description = extension._describe_button(context)
    assert description is not None
    assert description.root_mode == extension.ROOT_NODE
    assert description.owner_path == "outputs[0]"
    assert description.node_bl_idname == source.bl_idname
    assert description.node_name == source.name

    targets = extension._matching_node_targets(
        context,
        description.node_bl_idname,
        description.is_group_node,
        description.node_group_name,
        description.node_group_library,
        description.owner_path,
        description.owner_type,
        description.property_name,
        description.is_custom,
    )
    assert len(targets) == 2
    assert {item[0].name for item in targets} == {source.name, target.name}
    assert all(item[1].bl_rna.identifier == source_socket.bl_rna.identifier for item in targets)

    source.select = False
    target.select = False
    other.select = False
    context.selected_nodes = []
    targets = extension._matching_node_targets(
        context,
        description.node_bl_idname,
        description.is_group_node,
        description.node_group_name,
        description.node_group_library,
        description.owner_path,
        description.owner_type,
        description.property_name,
        description.is_custom,
        description.node_name,
    )
    assert len(targets) == 1
    assert targets[0][0] == source


def check_group_node_targets(extension, node_tree):
    node_tree.nodes.clear()
    first_group = bpy.data.node_groups.new("RandomizeValue_Group_A", "ShaderNodeTree")
    second_group = bpy.data.node_groups.new("RandomizeValue_Group_B", "ShaderNodeTree")
    for group in (first_group, second_group):
        group.interface.new_socket(
            name="Value",
            in_out="OUTPUT",
            socket_type="NodeSocketFloat",
        )

    source = node_tree.nodes.new("ShaderNodeGroup")
    matching = node_tree.nodes.new("ShaderNodeGroup")
    different = node_tree.nodes.new("ShaderNodeGroup")
    source.node_tree = first_group
    matching.node_tree = first_group
    different.node_tree = second_group
    source.select = matching.select = different.select = True

    source_socket = source.outputs[0]
    context = SimpleNamespace(
        button_pointer=source_socket,
        button_prop=source_socket.bl_rna.properties["default_value"],
        space_data=SimpleNamespace(edit_tree=node_tree, node_tree=node_tree),
        selected_nodes=[source, matching, different],
        object=None,
        active_object=None,
        selected_objects=[],
    )
    description = extension._describe_button(context)
    assert description is not None
    assert description.is_group_node
    assert description.node_group_name == first_group.name_full

    targets = extension._matching_node_targets(
        context,
        description.node_bl_idname,
        description.is_group_node,
        description.node_group_name,
        description.node_group_library,
        description.owner_path,
        description.owner_type,
        description.property_name,
        description.is_custom,
    )
    assert {item[0].name for item in targets} == {source.name, matching.name}


def check_menu_socket_enum_items(extension, node_tree):
    def randomize_second_item(nodes, source_socket):
        context = SimpleNamespace(
            button_pointer=source_socket,
            button_prop=source_socket.bl_rna.properties["default_value"],
            space_data=SimpleNamespace(edit_tree=node_tree, node_tree=node_tree),
            selected_nodes=nodes,
            object=None,
            active_object=None,
            selected_objects=[],
            view_layer=SimpleNamespace(update=lambda: None),
            window_manager=SimpleNamespace(windows=[]),
        )
        description = extension._describe_button(context)
        assert description is not None

        targets = extension._matching_node_targets(
            context,
            description.node_bl_idname,
            description.is_group_node,
            description.node_group_name,
            description.node_group_library,
            description.owner_path,
            description.owner_type,
            description.property_name,
            description.is_custom,
        )
        assert len(targets) == 2
        rng = random.Random(7)
        for _node, owner, property_name in targets:
            prop = extension._rna_property(owner, property_name)
            identifiers = extension._enum_identifiers(owner, prop)
            identifiers = extension.enum_items_in_range(identifiers, 1, 1)
            value = extension.random_value("ENUM", rng, enum_items=identifiers)
            extension._set_property_value(owner, property_name, False, value)

    node_tree.nodes.clear()

    menu_switches = [
        node_tree.nodes.new("GeometryNodeMenuSwitch"),
        node_tree.nodes.new("GeometryNodeMenuSwitch"),
    ]
    for node in menu_switches:
        node.select = True
    menu_socket = menu_switches[0].inputs[0]
    menu_prop = menu_socket.bl_rna.properties["default_value"]
    assert tuple(menu_prop.enum_items) == ()
    assert extension._enum_identifiers(menu_socket, menu_prop) == ("A", "B")
    randomize_second_item(menu_switches, menu_socket)
    assert all(node.inputs[0].default_value == "B" for node in menu_switches)

    node_tree.nodes.clear()
    transforms = [
        node_tree.nodes.new("GeometryNodeTransform"),
        node_tree.nodes.new("GeometryNodeTransform"),
    ]
    for node in transforms:
        node.select = True
    mode_socket = next(
        socket for socket in transforms[0].inputs if socket.bl_idname == "NodeSocketMenu"
    )
    mode_prop = mode_socket.bl_rna.properties["default_value"]
    original_value = mode_socket.default_value
    assert tuple(mode_prop.enum_items) == ()
    assert extension._enum_identifiers(mode_socket, mode_prop) == (
        "Components",
        "Matrix",
    )
    assert mode_socket.default_value == original_value
    randomize_second_item(transforms, mode_socket)
    assert all(
        next(
            socket for socket in node.inputs if socket.bl_idname == "NodeSocketMenu"
        ).default_value
        == "Matrix"
        for node in transforms
    )


extension = load_extension()
extension.register()

try:
    check_bone_targets(extension)
    check_animation_targets(extension)
    check_strip_targets(extension)
    check_shape_key_targets(extension)
    check_asset_metadata_targets(extension)
    check_node_interface_targets(extension)
    check_outliner_object_targets(extension)

    material = bpy.data.materials.new("RandomizeValue_ShaderMaterial")
    material.use_nodes = True
    check_node_tree_targets(extension, material.node_tree, "ShaderNodeValue", "ShaderNodeMath")
    check_group_node_targets(extension, material.node_tree)

    compositor_tree = bpy.data.node_groups.new(
        "RandomizeValue_CompositorTree",
        "CompositorNodeTree",
    )
    check_node_tree_targets(
        extension,
        compositor_tree,
        "CompositorNodeRGB",
        "CompositorNodeRGBToBW",
    )

    geometry_tree = bpy.data.node_groups.new(
        "RandomizeValue_GeometryTree",
        "GeometryNodeTree",
    )
    check_node_tree_targets(extension, geometry_tree, "ShaderNodeValue", "ShaderNodeMath")
    check_menu_socket_enum_items(extension, geometry_tree)

    bpy.ops.object.select_all(action="DESELECT")
    first_mesh = bpy.data.meshes.new("RandomizeValue_A_Mesh")
    second_mesh = bpy.data.meshes.new("RandomizeValue_B_Mesh")
    first_mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
    second_mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
    first = bpy.data.objects.new("RandomizeValue_A", first_mesh)
    second = bpy.data.objects.new("RandomizeValue_B", second_mesh)
    bpy.context.scene.collection.objects.link(first)
    bpy.context.scene.collection.objects.link(second)
    first.select_set(True)
    second.select_set(True)
    bpy.context.view_layer.objects.active = first

    display_items = tuple(
        item.identifier
        for item in first.bl_rna.properties["display_type"].enum_items
        if item.identifier
    )
    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        root_mode="OBJECT",
        owner_path="",
        owner_type="Object",
        property_name="display_type",
        property_label="Display As",
        value_type="ENUM",
        is_custom=False,
        array_length=0,
        enum_flag=False,
        subtype="NONE",
        unit="NONE",
        enum_index_min=1,
        enum_index_max=1,
        seed=42,
    )
    assert result == {"FINISHED"}, result
    assert first.display_type == display_items[1]
    assert second.display_type == display_items[1]

    common_arguments = {
        "root_mode": "OBJECT",
        "owner_path": "",
        "property_name": "location",
        "property_label": "Location",
        "value_type": "FLOAT",
        "is_custom": False,
        "array_length": 3,
        "enum_flag": False,
        "subtype": "TRANSLATION",
        "unit": "LENGTH",
        "seed": 42,
        "length_vector_min": vector_property((1.0, 10.0, 100.0)),
        "length_vector_max": vector_property((2.0, 20.0, 200.0)),
    }

    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        single_component=False,
        **common_arguments,
    )
    assert result == {"FINISHED"}, result
    assert tuple(first.location) != tuple(second.location)
    for value in (first.location, second.location):
        assert 1.0 <= value.x <= 2.0
        assert 10.0 <= value.y <= 20.0
        assert 100.0 <= value.z <= 200.0

    first_before = tuple(first.location)
    second_before = tuple(second.location)
    single_arguments = dict(common_arguments)
    single_arguments.update(
        component_index=1,
        length_min=-5.0,
        length_max=5.0,
    )
    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        single_component=True,
        **single_arguments,
    )
    assert result == {"FINISHED"}, result
    assert first.location.x == first_before[0]
    assert first.location.z == first_before[2]
    assert second.location.x == second_before[0]
    assert second.location.z == second_before[2]
    assert -5.0 <= first.location.y <= 5.0
    assert -5.0 <= second.location.y <= 5.0
    assert first.location.y != second.location.y

    first_before = tuple(first.location)
    second_before = tuple(second.location)
    delta_arguments = dict(common_arguments)
    delta_arguments.update(
        delta=True,
        length_vector_min=vector_property((1.0, 2.0, 3.0)),
        length_vector_max=vector_property((1.0, 2.0, 3.0)),
    )
    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        single_component=False,
        **delta_arguments,
    )
    assert result == {"FINISHED"}, result
    for before, after in ((first_before, first.location), (second_before, second.location)):
        assert abs(after.x - (before[0] + 1.0)) < 1.0e-6
        assert abs(after.y - (before[1] + 2.0)) < 1.0e-6
        assert abs(after.z - (before[2] + 3.0)) < 1.0e-6

    first_before = tuple(first.location)
    second_before = tuple(second.location)
    single_delta_arguments = dict(common_arguments)
    single_delta_arguments.update(
        delta=True,
        component_index=2,
        length_min=4.0,
        length_max=4.0,
    )
    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        single_component=True,
        **single_delta_arguments,
    )
    assert result == {"FINISHED"}, result
    for before, after in ((first_before, first.location), (second_before, second.location)):
        assert after.x == before[0]
        assert after.y == before[1]
        assert abs(after.z - (before[2] + 4.0)) < 1.0e-6

    source_group = bpy.data.node_groups.new("RandomizeValue_SourceGroup", "GeometryNodeTree")
    source_group.interface.new_socket(
        name="Geometry",
        in_out="INPUT",
        socket_type="NodeSocketGeometry",
    )
    source_first_socket = source_group.interface.new_socket(
        name="Amount",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    source_socket = source_group.interface.new_socket(
        name="Amount",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    source_group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    group_input = source_group.nodes.new("NodeGroupInput")
    group_output = source_group.nodes.new("NodeGroupOutput")
    combine_xyz = source_group.nodes.new("ShaderNodeCombineXYZ")
    set_position = source_group.nodes.new("GeometryNodeSetPosition")
    amount_output = next(
        socket
        for socket in group_input.outputs
        if socket.identifier == source_socket.identifier
    )
    source_group.links.new(group_input.outputs["Geometry"], set_position.inputs["Geometry"])
    source_group.links.new(amount_output, combine_xyz.inputs["X"])
    source_group.links.new(combine_xyz.outputs["Vector"], set_position.inputs["Offset"])
    source_group.links.new(set_position.outputs["Geometry"], group_output.inputs["Geometry"])
    source_modifier = first.modifiers.new("Geometry Nodes", "NODES")
    source_modifier.node_group = source_group

    target_modifier = second.modifiers.new("Geometry Nodes", "NODES")
    target_modifier.node_group = source_group

    different_name_mesh = bpy.data.meshes.new("RandomizeValue_DifferentName_Mesh")
    different_name_object = bpy.data.objects.new(
        "RandomizeValue_DifferentName",
        different_name_mesh,
    )
    bpy.context.scene.collection.objects.link(different_name_object)
    different_name_object.select_set(True)
    different_name_modifier = different_name_object.modifiers.new(
        "Other Geometry Nodes",
        "NODES",
    )
    different_name_modifier.node_group = source_group

    different_group = bpy.data.node_groups.new(
        "RandomizeValue_DifferentGroup",
        "GeometryNodeTree",
    )
    different_group.interface.new_socket(
        name="Amount",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    different_group_socket = different_group.interface.new_socket(
        name="Amount",
        in_out="INPUT",
        socket_type="NodeSocketFloat",
    )
    different_group_mesh = bpy.data.meshes.new("RandomizeValue_DifferentGroup_Mesh")
    different_group_object = bpy.data.objects.new(
        "RandomizeValue_DifferentGroup",
        different_group_mesh,
    )
    bpy.context.scene.collection.objects.link(different_group_object)
    different_group_object.select_set(True)
    different_group_modifier = different_group_object.modifiers.new("Geometry Nodes", "NODES")
    different_group_modifier.node_group = different_group

    source_first_before = source_modifier[source_first_socket.identifier]
    target_first_before = target_modifier[source_first_socket.identifier]
    different_name_before = different_name_modifier[source_socket.identifier]
    different_group_before = different_group_modifier[different_group_socket.identifier]
    result = bpy.ops.randomize_value.to_selected(
        "EXEC_DEFAULT",
        root_mode="OBJECT",
        owner_path=source_modifier.path_from_id(),
        owner_type="NodesModifier",
        property_name=source_socket.identifier,
        property_label="Amount",
        geometry_node_group_name=source_group.name_full,
        value_type="FLOAT",
        is_custom=True,
        array_length=0,
        enum_flag=False,
        subtype="NONE",
        unit="NONE",
        single_component=False,
        seed=73,
        float_min=20.0,
        float_max=30.0,
    )
    assert result == {"FINISHED"}, result
    source_value = source_modifier[source_socket.identifier]
    target_value = target_modifier[source_socket.identifier]
    assert 20.0 <= source_value <= 30.0
    assert 20.0 <= target_value <= 30.0
    assert source_value != target_value
    assert source_modifier[source_first_socket.identifier] == source_first_before
    assert target_modifier[source_first_socket.identifier] == target_first_before
    assert different_name_modifier[source_socket.identifier] == different_name_before
    assert different_group_modifier[different_group_socket.identifier] == different_group_before

    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj, expected_x in ((first, source_value), (second, target_value)):
        evaluated_object = obj.evaluated_get(depsgraph)
        evaluated_mesh = evaluated_object.to_mesh()
        try:
            assert len(evaluated_mesh.vertices) == 1
            assert abs(evaluated_mesh.vertices[0].co.x - expected_x) < 1.0e-5
        finally:
            evaluated_object.to_mesh_clear()
finally:
    extension.unregister()

print("Randomize Value Blender smoke test passed")
