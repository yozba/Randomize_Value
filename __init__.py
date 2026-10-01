"""Randomize Value Blender extension."""

_needs_reload = "bpy" in locals()

import ast
import importlib
import math
import random
import re
from dataclasses import dataclass
from typing import Any

import bpy
from bpy.props import (
    BoolProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    IntVectorProperty,
    StringProperty,
)

from . import randomize_core

if _needs_reload:
    randomize_core = importlib.reload(randomize_core)

SUPPORTED_TYPES = randomize_core.SUPPORTED_TYPES
clamp = randomize_core.clamp
enum_items_in_range = randomize_core.enum_items_in_range
ordered_bounds = randomize_core.ordered_bounds
random_value = randomize_core.random_value


bl_info = {
    "name": "Randomize Value",
    "author": "yozba",
    "version": (0, 7, 2),
    "blender": (4, 2, 0),
    "location": "Property context menus",
    "description": "Randomize a clicked property across selected objects or nodes",
    "category": "Object",
}


ROOT_OBJECT = "OBJECT"
ROOT_DATA = "DATA"
ROOT_MATERIAL = "MATERIAL"
ROOT_MATERIAL_NODES = "MATERIAL_NODES"
ROOT_NODE = "NODE"
MAX_VECTOR_SIZE = 32


@dataclass(frozen=True)
class TargetDescription:
    root_mode: str
    owner_path: str
    owner_type: str
    node_bl_idname: str
    node_name: str
    is_group_node: bool
    node_group_name: str
    node_group_library: str
    property_name: str
    property_label: str
    geometry_node_group_name: str
    value_type: str
    is_custom: bool
    array_length: int
    enum_flag: bool
    subtype: str
    unit: str


def _same_rna_value(first: Any, second: Any) -> bool:
    if first is None or second is None:
        return False
    if first is second:
        return True
    try:
        return first.as_pointer() == second.as_pointer()
    except (AttributeError, ReferenceError):
        return False


def _root_candidates(obj: bpy.types.Object) -> tuple[tuple[str, Any], ...]:
    material = getattr(obj, "active_material", None)
    return (
        (ROOT_OBJECT, obj),
        (ROOT_DATA, getattr(obj, "data", None)),
        (ROOT_MATERIAL, material),
        (ROOT_MATERIAL_NODES, getattr(material, "node_tree", None)),
    )


def _find_root_mode(obj: bpy.types.Object, pointer: Any) -> str | None:
    id_data = getattr(pointer, "id_data", None)
    for mode, candidate in _root_candidates(obj):
        # ID instances are not guaranteed to expose themselves through
        # ``id_data`` in every UI context, so compare the button pointer too.
        if _same_rna_value(pointer, candidate) or _same_rna_value(id_data, candidate):
            return mode
    return None


def _source_objects(context: bpy.types.Context) -> list[bpy.types.Object]:
    """Return likely owners first, including pinned Properties editors."""

    objects: list[bpy.types.Object] = []
    for obj in (
        getattr(context, "object", None),
        getattr(context, "active_object", None),
        *(getattr(context, "selected_objects", ()) or ()),
    ):
        if obj is not None and obj not in objects:
            objects.append(obj)
    return objects


def _root_for_object(obj: bpy.types.Object, root_mode: str) -> Any | None:
    for mode, candidate in _root_candidates(obj):
        if mode == root_mode:
            return candidate
    return None


def _resolve_owner(obj: bpy.types.Object, root_mode: str, owner_path: str) -> Any | None:
    root = _root_for_object(obj, root_mode)
    if root is None:
        return None
    if not owner_path:
        return root
    try:
        return root.path_resolve(owner_path)
    except (AttributeError, ValueError, ReferenceError):
        return None


def _node_tree_from_context(context: bpy.types.Context) -> Any | None:
    space_data = getattr(context, "space_data", None)
    return getattr(space_data, "edit_tree", None) or getattr(space_data, "node_tree", None)


def _find_node_owner(pointer: Any, context: bpy.types.Context) -> tuple[Any, str] | None:
    if isinstance(pointer, bpy.types.Node):
        return pointer, ""
    if not isinstance(pointer, bpy.types.NodeSocket):
        return None

    node_tree = getattr(pointer, "id_data", None) or _node_tree_from_context(context)
    for node in getattr(node_tree, "nodes", ()):
        for collection_name in ("inputs", "outputs"):
            for index, socket in enumerate(getattr(node, collection_name, ())):
                if _same_rna_value(pointer, socket):
                    return node, f"{collection_name}[{index}]"
    return None


def _selected_nodes(context: bpy.types.Context) -> list[Any]:
    nodes = list(getattr(context, "selected_nodes", ()) or ())
    if not nodes:
        node_tree = _node_tree_from_context(context)
        nodes = [node for node in getattr(node_tree, "nodes", ()) if getattr(node, "select", False)]
    return sorted(nodes, key=lambda node: getattr(node, "name", ""))


def _rna_property(owner: Any, property_name: str) -> Any | None:
    try:
        return owner.bl_rna.properties[property_name]
    except (AttributeError, KeyError, TypeError):
        return None


def _get_property_value(owner: Any, property_name: str, is_custom: bool) -> Any:
    if is_custom:
        return owner[property_name]
    return getattr(owner, property_name)


def _set_property_value(owner: Any, property_name: str, is_custom: bool, value: Any) -> None:
    if is_custom:
        owner[property_name] = value
    else:
        setattr(owner, property_name, value)


def _is_geometry_nodes_modifier(value: Any) -> bool:
    return getattr(value, "type", "") == "NODES" and hasattr(value, "node_group")


def _geometry_input_sockets(modifier: Any):
    if not _is_geometry_nodes_modifier(modifier):
        return ()
    node_group = getattr(modifier, "node_group", None)
    interface = getattr(node_group, "interface", None)
    items = getattr(interface, "items_tree", ())
    return tuple(
        item
        for item in items
        if getattr(item, "item_type", "") == "SOCKET"
        and getattr(item, "in_out", "") == "INPUT"
    )


def _geometry_socket_name(modifier: Any, property_name: str) -> str:
    for socket in _geometry_input_sockets(modifier):
        if getattr(socket, "identifier", "") == property_name:
            return getattr(socket, "name", "")
    return ""


def _custom_property_name(pointer: Any, identifier: str) -> str | None:
    try:
        if identifier in pointer.keys() and _rna_property(pointer, identifier) is None:
            return identifier
    except (AttributeError, TypeError, ReferenceError):
        pass

    # Some Blender controls expose a custom-property identifier as ["name"].
    if identifier.startswith('["') and identifier.endswith('"]'):
        name = identifier[2:-2].replace(r'\"', '"').replace(r"\\", "\\")
        try:
            if name in pointer.keys():
                return name
        except (AttributeError, TypeError, ReferenceError):
            pass
    return None


def _describe_button(context: bpy.types.Context) -> TargetDescription | None:
    pointer = getattr(context, "button_pointer", None)
    prop = getattr(context, "button_prop", None)
    if prop is None:
        return None

    value_type = getattr(prop, "type", "")
    # Do not reject based on Property.is_readonly here. Some compound UI
    # controls expose conservative metadata even though their owner accepts
    # assignment (Object.location is the important example). Actual writes
    # are attempted safely in execute() and unsupported targets are skipped.
    if value_type not in SUPPORTED_TYPES:
        return None

    identifier = getattr(prop, "identifier", "")
    custom_name = _custom_property_name(pointer, identifier) if pointer is not None else None
    is_custom = custom_name is not None
    property_name = custom_name if is_custom else identifier
    if not property_name:
        return None

    node_owner = _find_node_owner(pointer, context)
    if node_owner is not None:
        source_node, owner_path = node_owner
        try:
            current_value = _get_property_value(pointer, property_name, is_custom)
        except (AttributeError, KeyError, TypeError, ValueError, ReferenceError):
            return None

        array_length = int(getattr(prop, "array_length", 0))
        if not isinstance(current_value, (str, bytes, bool, int, float, set)):
            try:
                current_items = list(current_value)
                if all(isinstance(item, (bool, int, float)) for item in current_items):
                    array_length = len(current_items)
            except (TypeError, ReferenceError):
                pass
        if array_length > MAX_VECTOR_SIZE:
            return None

        label = getattr(pointer, "name", "") if isinstance(pointer, bpy.types.NodeSocket) else ""
        source_node_group = getattr(source_node, "node_tree", None)
        source_node_group_library = getattr(source_node_group, "library", None)
        return TargetDescription(
            root_mode=ROOT_NODE,
            owner_path=owner_path,
            owner_type=_rna_type_name(pointer),
            node_bl_idname=getattr(source_node, "bl_idname", ""),
            node_name=getattr(source_node, "name", ""),
            is_group_node=hasattr(source_node, "node_tree"),
            node_group_name=getattr(source_node_group, "name_full", ""),
            node_group_library=getattr(source_node_group_library, "filepath", ""),
            property_name=property_name,
            property_label=label or getattr(prop, "name", "") or property_name,
            geometry_node_group_name="",
            value_type=value_type,
            is_custom=is_custom,
            array_length=array_length,
            enum_flag=bool(getattr(prop, "is_enum_flag", False)),
            subtype=getattr(prop, "subtype", "NONE"),
            unit=getattr(prop, "unit", "NONE"),
        )

    root_mode = None
    root_source_object = None
    source_pointer = pointer
    source_objects = _source_objects(context)
    if pointer is not None:
        for source_object in source_objects:
            root_mode = _find_root_mode(source_object, pointer)
            if root_mode is not None:
                root_source_object = source_object
                break

    # Direct object properties such as Location should remain available even
    # if a particular UI context does not expose a useful pointer ``id_data``.
    if root_mode is None and not is_custom:
        for source_object in source_objects:
            source_prop = _rna_property(source_object, identifier)
            if source_prop is not None and getattr(source_prop, "type", "") == value_type:
                root_mode = ROOT_OBJECT
                root_source_object = source_object
                source_pointer = source_object
                break
    if root_mode is None:
        return None

    try:
        root = _root_for_object(root_source_object, root_mode)
        owner_path = "" if _same_rna_value(source_pointer, root) else source_pointer.path_from_id()
        current_value = _get_property_value(source_pointer, property_name, is_custom)
    except (AttributeError, KeyError, TypeError, ValueError, ReferenceError):
        return None

    array_length = int(getattr(prop, "array_length", 0))
    if not isinstance(current_value, (str, bytes, bool, int, float, set)):
        try:
            current_items = list(current_value)
            if all(isinstance(item, (bool, int, float)) for item in current_items):
                # Dynamic ID properties can report a stale or generic RNA
                # array length. The actual flat value is authoritative.
                array_length = len(current_items)
        except (TypeError, ReferenceError):
            pass
    if array_length > MAX_VECTOR_SIZE:
        return None

    geometry_socket_name = _geometry_socket_name(source_pointer, property_name) if is_custom else ""
    geometry_node_group_name = ""
    if geometry_socket_name:
        node_group = getattr(source_pointer, "node_group", None)
        geometry_node_group_name = getattr(node_group, "name_full", "")

    return TargetDescription(
        root_mode=root_mode,
        owner_path=owner_path,
        owner_type=_rna_type_name(source_pointer),
        node_bl_idname="",
        node_name="",
        is_group_node=False,
        node_group_name="",
        node_group_library="",
        property_name=property_name,
        property_label=geometry_socket_name or getattr(prop, "name", "") or property_name,
        geometry_node_group_name=geometry_node_group_name,
        value_type=value_type,
        is_custom=is_custom,
        array_length=array_length,
        enum_flag=bool(getattr(prop, "is_enum_flag", False)),
        subtype=getattr(prop, "subtype", "NONE"),
        unit=getattr(prop, "unit", "NONE"),
    )


def _rna_type_name(value: Any) -> str:
    if value is None:
        return "None"
    return getattr(getattr(value, "bl_rna", None), "identifier", type(value).__name__)


def _button_diagnostics(context: bpy.types.Context) -> str:
    pointer = getattr(context, "button_pointer", None)
    prop = getattr(context, "button_prop", None)
    identifier = getattr(prop, "identifier", "")
    value_type = getattr(prop, "type", "")
    id_data = getattr(pointer, "id_data", None) if pointer is not None else None
    source_parts = []
    for obj in _source_objects(context):
        source_prop = _rna_property(obj, identifier) if identifier else None
        root_mode = _find_root_mode(obj, pointer) if pointer is not None else None
        source_parts.append(
            f"{_rna_type_name(obj)}/{getattr(source_prop, 'type', 'missing')}/{root_mode}"
        )

    path_result = "not-tested"
    if pointer is not None:
        try:
            path_result = repr(pointer.path_from_id())
        except Exception as error:  # Diagnostics must survive unusual RNA proxies.
            path_result = f"{type(error).__name__}: {error}"

    node_owner = _find_node_owner(pointer, context)
    node_result = "None"
    if node_owner is not None:
        node, node_path = node_owner
        node_result = f"{getattr(node, 'bl_idname', '')}/{getattr(node, 'name', '')}/{node_path}"

    return "; ".join(
        (
            "Randomize Value 0.7.2",
            f"area={getattr(getattr(context, 'area', None), 'type', 'None')}",
            f"property={identifier!r}",
            f"property_type={value_type!r}",
            f"property_readonly={getattr(prop, 'is_readonly', 'unknown')!r}",
            f"pointer={_rna_type_name(pointer)}",
            f"id_data={_rna_type_name(id_data)}",
            f"pointer_path={path_result}",
            f"context_object={_rna_type_name(getattr(context, 'object', None))}",
            f"active_object={_rna_type_name(getattr(context, 'active_object', None))}",
            f"node={node_result!r}",
            f"selected_nodes={len(_selected_nodes(context))}",
            f"sources={source_parts!r}",
        )
    )


def _button_array_index(context: bpy.types.Context) -> int:
    """Read the hovered array index through Blender's own data-path operator."""

    clipboard = context.window_manager.clipboard
    try:
        try:
            result = bpy.ops.ui.copy_data_path_button("EXEC_DEFAULT", full_path=False)
        except RuntimeError:
            return -1
        if result != {"FINISHED"}:
            return -1
        data_path = context.window_manager.clipboard
    finally:
        context.window_manager.clipboard = clipboard

    match = re.search(r"\[(\d+)\]\s*$", data_path)
    return int(match.group(1)) if match else -1


def _owner_identity(owner: Any) -> int:
    try:
        return owner.as_pointer()
    except (AttributeError, ReferenceError):
        return id(owner)


def _matching_node_targets(
    context: bpy.types.Context,
    node_bl_idname: str,
    is_group_node: bool,
    node_group_name: str,
    node_group_library: str,
    owner_path: str,
    owner_type: str,
    property_name: str,
    is_custom: bool,
    source_node_name: str = "",
) -> list[tuple[Any, Any, str]]:
    targets: list[tuple[Any, Any, str]] = []
    seen: set[int] = set()
    nodes = _selected_nodes(context)
    if not nodes and source_node_name:
        node_tree = _node_tree_from_context(context)
        node_collection = getattr(node_tree, "nodes", None)
        source_node = node_collection.get(source_node_name) if node_collection is not None else None
        if source_node is not None:
            nodes = [source_node]

    for node in nodes:
        if getattr(node, "bl_idname", "") != node_bl_idname:
            continue
        if is_group_node:
            target_node_group = getattr(node, "node_tree", None)
            if not node_group_name:
                if target_node_group is not None:
                    continue
            else:
                target_library = getattr(target_node_group, "library", None)
                if (
                    getattr(target_node_group, "name_full", "") != node_group_name
                    or getattr(target_library, "filepath", "") != node_group_library
                ):
                    continue
        try:
            owner = node if not owner_path else node.path_resolve(owner_path)
        except (AttributeError, ValueError, ReferenceError):
            continue
        if owner_type and _rna_type_name(owner) != owner_type:
            continue
        identity = _owner_identity(owner)
        if identity in seen:
            continue
        try:
            _get_property_value(owner, property_name, is_custom)
        except (AttributeError, KeyError, TypeError, ReferenceError):
            continue
        seen.add(identity)
        targets.append((node, owner, property_name))
    return targets


def _tag_property_update(target: Any, owner: Any) -> None:
    """Tag the target and property-owning data-block for dependency evaluation."""

    tagged: set[int] = set()
    for data_block in (target, getattr(owner, "id_data", None), owner):
        update_tag = getattr(data_block, "update_tag", None)
        if update_tag is None:
            continue
        identity = _owner_identity(data_block)
        if identity in tagged:
            continue
        try:
            update_tag()
        except (RuntimeError, TypeError, ReferenceError):
            continue
        tagged.add(identity)


def _redraw_editors(context: bpy.types.Context) -> None:
    window_manager = getattr(context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type in {"VIEW_3D", "NODE_EDITOR"}:
                area.tag_redraw()


def _selected_objects(context: bpy.types.Context) -> list[bpy.types.Object]:
    objects = list(getattr(context, "selected_objects", ()) or ())
    active = getattr(context, "active_object", None)
    if active is not None and active not in objects:
        objects.append(active)
    return sorted(objects, key=lambda item: item.name_full)


def _hard_numeric_interval(prop: Any, value_type: str) -> tuple[float | int, float | int]:
    if value_type == "INT":
        fallback = (-2_147_483_648, 2_147_483_647)
    else:
        fallback = (-1.0e30, 1.0e30)
    try:
        return prop.hard_min, prop.hard_max
    except AttributeError:
        return fallback


def _enum_identifiers_from_assignment(owner: Any, property_name: str) -> tuple[str, ...]:
    """Read a dynamic enum's identifiers from RNA's validation error.

    NodeSocketMenu keeps its runtime items outside PropertyRNA, so
    ``prop.enum_items`` is empty. RNA still reports the valid identifiers
    when it rejects an invalid assignment. The deliberately overlong value
    cannot be a node menu item and the failed assignment leaves the socket
    unchanged.
    """

    invalid_identifier = "__RANDOMIZE_VALUE_INVALID_" + ("X" * 256)
    try:
        setattr(owner, property_name, invalid_identifier)
    except (TypeError, ValueError) as error:
        match = re.search(r"not found in (\(.*\))$", str(error), re.DOTALL)
        if match is None:
            return ()
        try:
            identifiers = ast.literal_eval(match.group(1))
        except (SyntaxError, ValueError):
            return ()
        if isinstance(identifiers, tuple) and all(
            isinstance(identifier, str) for identifier in identifiers
        ):
            return identifiers
    return ()


def _enum_identifiers(owner: Any, prop: Any) -> tuple[str, ...]:
    try:
        identifiers = tuple(item.identifier for item in prop.enum_items if item.identifier)
    except (AttributeError, ReferenceError):
        identifiers = ()
    if identifiers:
        return identifiers

    node = getattr(owner, "node", None)
    enum_definition = getattr(node, "enum_definition", None)
    for item_owner in (enum_definition, node, owner):
        try:
            identifiers = tuple(
                item.name for item in item_owner.enum_items if item.name
            )
        except (AttributeError, ReferenceError):
            continue
        if identifiers:
            return identifiers

    if _rna_type_name(owner) == "NodeSocketMenu":
        return _enum_identifiers_from_assignment(owner, prop.identifier)
    return ()


class RANDOMIZEVALUE_OT_to_selected(bpy.types.Operator):
    """Assign deterministic random values to this property on selected objects"""

    bl_idname = "randomize_value.to_selected"
    bl_label = "Randomize to Selected"
    bl_options = {"REGISTER", "UNDO"}

    root_mode: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    owner_path: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    owner_type: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    node_bl_idname: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    node_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    is_group_node: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    node_group_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    node_group_library: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    property_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    property_label: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    geometry_node_group_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    value_type: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    is_custom: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    array_length: IntProperty(options={"HIDDEN", "SKIP_SAVE"})
    enum_flag: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    subtype: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    unit: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    single_component: BoolProperty(options={"HIDDEN", "SKIP_SAVE"})
    component_index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    delta: BoolProperty(
        name="Delta",
        description="Add a random offset to each current value",
        default=False,
    )

    seed: IntProperty(
        name="Seed",
        description="Seed used for reproducible values",
        default=0,
    )
    probability: FloatProperty(
        name="True Probability",
        description="Probability that each Boolean value becomes true",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    enum_index_min: IntProperty(
        name="Minimum Enum Index",
        description="Inclusive minimum item index; negative values count from the end",
        default=0,
    )
    enum_index_max: IntProperty(
        name="Maximum Enum Index",
        description="Inclusive maximum item index; -1 means the last item",
        default=-1,
    )
    int_min: IntProperty(name="Minimum", default=0)
    int_max: IntProperty(name="Maximum", default=1)
    float_min: FloatProperty(name="Minimum", default=0.0)
    float_max: FloatProperty(name="Maximum", default=1.0)
    angle_min: FloatProperty(name="Minimum", default=0.0, unit="ROTATION")
    angle_max: FloatProperty(name="Maximum", default=math.radians(15.0), unit="ROTATION")
    length_min: FloatProperty(name="Minimum", default=0.0, unit="LENGTH")
    length_max: FloatProperty(name="Maximum", default=1.0, unit="LENGTH")
    int_vector_min: IntVectorProperty(
        name="Minimum",
        size=MAX_VECTOR_SIZE,
        default=(0,) * MAX_VECTOR_SIZE,
    )
    int_vector_max: IntVectorProperty(
        name="Maximum",
        size=MAX_VECTOR_SIZE,
        default=(1,) * MAX_VECTOR_SIZE,
    )
    float_vector_min: FloatVectorProperty(
        name="Minimum",
        size=MAX_VECTOR_SIZE,
        default=(0.0,) * MAX_VECTOR_SIZE,
    )
    float_vector_max: FloatVectorProperty(
        name="Maximum",
        size=MAX_VECTOR_SIZE,
        default=(1.0,) * MAX_VECTOR_SIZE,
    )
    angle_vector_min: FloatVectorProperty(
        name="Minimum",
        size=MAX_VECTOR_SIZE,
        default=(0.0,) * MAX_VECTOR_SIZE,
        unit="ROTATION",
    )
    angle_vector_max: FloatVectorProperty(
        name="Maximum",
        size=MAX_VECTOR_SIZE,
        default=(math.radians(15.0),) * MAX_VECTOR_SIZE,
        unit="ROTATION",
    )
    length_vector_min: FloatVectorProperty(
        name="Minimum",
        size=MAX_VECTOR_SIZE,
        default=(0.0,) * MAX_VECTOR_SIZE,
        unit="LENGTH",
    )
    length_vector_max: FloatVectorProperty(
        name="Maximum",
        size=MAX_VECTOR_SIZE,
        default=(1.0,) * MAX_VECTOR_SIZE,
        unit="LENGTH",
    )
    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return (
            getattr(context, "active_object", None) is not None
            or _node_tree_from_context(context) is not None
        )

    def _owner_and_property(self, obj: bpy.types.Object) -> tuple[Any, str] | None:
        owner = _resolve_owner(obj, self.root_mode, self.owner_path)
        if owner is None:
            return None
        if self.owner_type and _rna_type_name(owner) != self.owner_type:
            return None
        if self.geometry_node_group_name:
            node_group = getattr(owner, "node_group", None)
            source_node_group = bpy.data.node_groups.get(self.geometry_node_group_name)
            if (
                not _is_geometry_nodes_modifier(owner)
                or source_node_group is None
                or not _same_rna_value(node_group, source_node_group)
            ):
                return None
        return owner, self.property_name

    def _node_targets(self, context: bpy.types.Context) -> list[tuple[Any, Any, str]]:
        return _matching_node_targets(
            context,
            self.node_bl_idname,
            self.is_group_node,
            self.node_group_name,
            self.node_group_library,
            self.owner_path,
            self.owner_type,
            self.property_name,
            self.is_custom,
            self.node_name,
        )

    def _targets(self, context: bpy.types.Context) -> list[tuple[Any, Any, str]]:
        if self.root_mode == ROOT_NODE:
            return self._node_targets(context)

        targets: list[tuple[Any, Any, str]] = []
        seen: set[int] = set()
        for obj in _selected_objects(context):
            resolved = self._owner_and_property(obj)
            if resolved is None:
                continue
            owner, property_name = resolved
            identity = _owner_identity(owner)
            if identity in seen:
                continue
            try:
                _get_property_value(owner, property_name, self.is_custom)
            except (AttributeError, KeyError, TypeError, ReferenceError):
                continue
            seen.add(identity)
            targets.append((obj, owner, property_name))
        return targets

    def _target_name(self) -> str:
        return "node" if self.root_mode == ROOT_NODE else "object"

    def _range_property_names(self) -> tuple[str, str]:
        use_vector_range = self.array_length > 0 and not self.single_component
        vector_suffix = "_vector" if use_vector_range else ""
        if self.value_type == "INT":
            stem = f"int{vector_suffix}"
            return f"{stem}_min", f"{stem}_max"
        if self.unit == "ROTATION":
            stem = f"angle{vector_suffix}"
            return f"{stem}_min", f"{stem}_max"
        if self.unit == "LENGTH":
            stem = f"length{vector_suffix}"
            return f"{stem}_min", f"{stem}_max"
        stem = f"float{vector_suffix}"
        return f"{stem}_min", f"{stem}_max"

    def _draw_vector_range(self, layout: bpy.types.UILayout, property_name: str, label: str) -> None:
        split = layout.split(factor=0.4, align=True)
        labels = split.column(align=True)
        labels.alignment = "RIGHT"
        labels.label(text=label)
        for _index in range(1, self.array_length):
            labels.label(text="")
        column = split.column(align=True)
        for index in range(self.array_length):
            column.prop(self, property_name, index=index, text="")

    def _draw_labeled_property(
        self,
        layout: bpy.types.UILayout,
        property_name: str,
        label: str,
        *,
        slider: bool = False,
    ) -> None:
        split = layout.split(factor=0.4, align=True)
        label_column = split.column(align=True)
        value_column = split.column(align=True)
        label_column.alignment = "RIGHT"
        label_column.label(text=label)
        value_column.prop(self, property_name, text="", slider=slider)

    def _draw_aligned_checkbox(
        self,
        layout: bpy.types.UILayout,
        property_name: str,
        label: str,
    ) -> None:
        split = layout.split(factor=0.4, align=True)
        label_column = split.column(align=True)
        value_column = split.column(align=True)
        label_column.label(text="")
        value_column.prop(self, property_name, text=label)

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if not 0 <= self.array_length <= MAX_VECTOR_SIZE:
            self.report({"WARNING"}, f"Arrays longer than {MAX_VECTOR_SIZE} items are not supported")
            return {"CANCELLED"}

        targets = self._targets(context)
        if not targets:
            self.report({"WARNING"}, f"No selected {self._target_name()} has this property")
            return {"CANCELLED"}

        if self.single_component:
            if self.component_index < 0:
                self.component_index = _button_array_index(context)
            if not 0 <= self.component_index < self.array_length:
                self.report({"WARNING"}, "Right-click an individual vector component")
                return {"CANCELLED"}

        title = (
            "Randomize Single to Selected"
            if self.single_component
            else "Randomize to Selected"
        )
        return context.window_manager.invoke_props_dialog(self, width=240, title=title)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_decorate = False
        if self.value_type == "BOOLEAN":
            self._draw_labeled_property(
                layout,
                "probability",
                "True Probability",
                slider=True,
            )
        elif self.value_type == "ENUM":
            self._draw_labeled_property(layout, "enum_index_min", "Min Index")
            self._draw_labeled_property(layout, "enum_index_max", "Max Index")
        elif self.value_type in {"INT", "FLOAT"}:
            self._draw_aligned_checkbox(layout, "delta", "Delta")
            low_name, high_name = self._range_property_names()
            column = layout.column(align=True)
            if self.array_length > 0 and not self.single_component:
                self._draw_vector_range(column, low_name, "Min")
                column.separator(factor=0.35)
                self._draw_vector_range(column, high_name, "Max")
            else:
                self._draw_labeled_property(column, low_name, "Min")
                self._draw_labeled_property(column, high_name, "Max")
        self._draw_labeled_property(layout, "seed", "Seed")

    def execute(self, context: bpy.types.Context) -> set[str]:
        if not 0 <= self.array_length <= MAX_VECTOR_SIZE:
            self.report({"WARNING"}, f"Arrays longer than {MAX_VECTOR_SIZE} items are not supported")
            return {"CANCELLED"}

        targets = self._targets(context)
        if not targets:
            self.report({"WARNING"}, f"No selected {self._target_name()} has this property")
            return {"CANCELLED"}
        if self.single_component and not 0 <= self.component_index < self.array_length:
            self.report({"WARNING"}, "No valid vector component was selected")
            return {"CANCELLED"}

        minimum: float | int | list[float | int] = 0
        maximum: float | int | list[float | int] = 1
        use_delta = self.delta and self.value_type in {"INT", "FLOAT"}
        if self.value_type in {"INT", "FLOAT"}:
            low_name, high_name = self._range_property_names()
            prop = _rna_property(targets[0][1], targets[0][2])
            hard_low, hard_high = _hard_numeric_interval(prop, self.value_type)
            if self.array_length > 0 and not self.single_component:
                requested_lows = list(getattr(self, low_name))[: self.array_length]
                requested_highs = list(getattr(self, high_name))[: self.array_length]
                minimum = []
                maximum = []
                for requested_low, requested_high in zip(requested_lows, requested_highs):
                    requested_low, requested_high = ordered_bounds(requested_low, requested_high)
                    if use_delta:
                        minimum.append(requested_low)
                        maximum.append(requested_high)
                    else:
                        minimum.append(clamp(requested_low, hard_low, hard_high))
                        maximum.append(clamp(requested_high, hard_low, hard_high))
            else:
                requested_low, requested_high = ordered_bounds(
                    getattr(self, low_name), getattr(self, high_name)
                )
                if use_delta:
                    minimum, maximum = requested_low, requested_high
                else:
                    minimum = clamp(requested_low, hard_low, hard_high)
                    maximum = clamp(requested_high, hard_low, hard_high)
                    minimum, maximum = ordered_bounds(minimum, maximum)

        rng = random.Random(self.seed)
        changed = 0
        skipped = 0
        for _obj, owner, property_name in targets:
            prop = _rna_property(owner, property_name)
            enum_items = _enum_identifiers(owner, prop) if self.value_type == "ENUM" else ()
            if enum_items:
                enum_items = enum_items_in_range(
                    enum_items,
                    self.enum_index_min,
                    self.enum_index_max,
                )
            try:
                if self.single_component:
                    value = list(_get_property_value(owner, property_name, self.is_custom))
                    generated = random_value(
                        self.value_type,
                        rng,
                        minimum=minimum,
                        maximum=maximum,
                        probability=self.probability,
                        enum_items=enum_items,
                        enum_flag=self.enum_flag,
                    )
                    if use_delta:
                        hard_low, hard_high = _hard_numeric_interval(prop, self.value_type)
                        generated = clamp(
                            value[self.component_index] + generated,
                            hard_low,
                            hard_high,
                        )
                    value[self.component_index] = generated
                else:
                    value = random_value(
                        self.value_type,
                        rng,
                        array_length=self.array_length,
                        minimum=minimum,
                        maximum=maximum,
                        probability=self.probability,
                        enum_items=enum_items,
                        enum_flag=self.enum_flag,
                    )
                    if use_delta:
                        current = _get_property_value(owner, property_name, self.is_custom)
                        hard_low, hard_high = _hard_numeric_interval(prop, self.value_type)
                        if self.array_length > 0:
                            value = [
                                clamp(current[index] + component, hard_low, hard_high)
                                for index, component in enumerate(value)
                            ]
                        else:
                            value = clamp(current + value, hard_low, hard_high)
                _set_property_value(owner, property_name, self.is_custom, value)
            except (AttributeError, KeyError, TypeError, ValueError, ReferenceError):
                skipped += 1
                continue
            _tag_property_update(_obj, owner)
            changed += 1

        if changed == 0:
            self.report({"WARNING"}, "The property could not be changed")
            return {"CANCELLED"}

        try:
            context.view_layer.update()
        except (AttributeError, RuntimeError, ReferenceError):
            pass
        _redraw_editors(context)

        message = f"Randomized {self.property_label} on {changed} data-block(s)"
        if skipped:
            message += f"; skipped {skipped}"
        self.report({"INFO"}, message)
        return {"FINISHED"}


class RANDOMIZEVALUE_OT_copy_diagnostics(bpy.types.Operator):
    """Copy diagnostic context data for an unavailable property"""

    bl_idname = "randomize_value.copy_diagnostics"
    bl_label = "Copy Randomize Value Diagnostics"

    details: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context: bpy.types.Context) -> set[str]:
        context.window_manager.clipboard = self.details
        self.report({"INFO"}, "Randomize Value diagnostics copied to clipboard")
        return {"FINISHED"}


def _draw_button_context_menu(self: bpy.types.Menu, context: bpy.types.Context) -> None:
    description = _describe_button(context)
    if description is None:
        # Keep a diagnostic entry for supported scalar controls. If this
        # appears, the extension and menu hook are loaded but the owner cannot
        # be mapped to selected objects or nodes.
        prop = getattr(context, "button_prop", None)
        if (
            getattr(prop, "type", "") in SUPPORTED_TYPES
            and (
                getattr(context, "active_object", None) is not None
                or _node_tree_from_context(context) is not None
            )
        ):
            self.layout.separator()
            operator = self.layout.operator(
                RANDOMIZEVALUE_OT_copy_diagnostics.bl_idname,
                text="Copy Randomize Value Diagnostics",
                icon="COPYDOWN",
            )
            operator.details = _button_diagnostics(context)
        return

    layout = self.layout
    layout.separator()
    layout.operator_context = "INVOKE_DEFAULT"
    menu_items = [("Randomize to Selected", False)]
    if description.array_length > 0:
        menu_items.append(("Randomize Single to Selected", True))
    for text, single_component in menu_items:
        operator = layout.operator(
            RANDOMIZEVALUE_OT_to_selected.bl_idname,
            text=text,
        )
        for field in TargetDescription.__dataclass_fields__:
            setattr(operator, field, getattr(description, field))
        operator.single_component = single_component


classes = (
    RANDOMIZEVALUE_OT_to_selected,
    RANDOMIZEVALUE_OT_copy_diagnostics,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.UI_MT_button_context_menu.append(_draw_button_context_menu)
    print("[Randomize Value] 0.7.2 registered")


def unregister() -> None:
    try:
        bpy.types.UI_MT_button_context_menu.remove(_draw_button_context_menu)
    except ValueError:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[Randomize Value] unregistered")
