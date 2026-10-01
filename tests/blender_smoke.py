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
