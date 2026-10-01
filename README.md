# Randomize Value

Randomize Value is a Blender extension that assigns reproducible random values to the same
property across selected objects or selected nodes.

## Requirements

- Blender 4.2 or newer

## Installation

1. Package the extension with Blender's extension builder, or create a ZIP containing
   `blender_manifest.toml`, `__init__.py`, `randomize_core.py`, and `LICENSE` at its root.
2. In Blender, open **Edit > Preferences > Get Extensions**, use the menu in the top-right,
   and choose **Install from Disk**.
3. Select the ZIP and enable **Randomize Value** if necessary.

## Usage

1. Select all objects to change and make one of them active.
2. In the Properties editor (or another property field, such as the 3D View sidebar),
   right-click a supported property.
3. Choose one of the following commands:
   - **Randomize to Selected** generates a different value for each target.
   - **Randomize Single to Selected** randomizes only the vector component that was right-clicked.
4. Set the range or probability and a seed, then confirm.

In the Shader, Compositor, and Geometry Node editors, right-click a node property or socket value.
Selected nodes with the same Blender node type are targeted. Socket properties are matched by
their position within the node and RNA type, not by their visible name alone. Group nodes must also
reference the same Node Tree data-block (including the linked-library source when applicable).
Geometry Nodes Menu sockets are supported, including editable Menu Switch items and fixed menus.

For numeric properties, enable **Delta** to add the Min/Max random value to each object's
current value. With Delta disabled, the same Min/Max fields are used as an absolute range.

The popup is selected automatically from the clicked property's RNA type:

- **Float / Integer:** inclusive minimum and maximum (float sampling is continuous).
- **Boolean:** probability of `true`.
- **Enum:** a random choice from the inclusive Min Index / Max Index range. Negative indices count
  from the end, so the default `0` to `-1` includes every item. Enum flags receive a random subset
  drawn only from that range.
- **Array / Vector:** every component has its own vertically stacked minimum and maximum field.

Object properties and nested object-owned data such as modifiers and constraints are supported.
Equivalent properties on Object Data, active materials, and active material node trees are also
supported. Geometry Nodes modifier inputs follow Blender's Copy to Selected matching rules: the
modifier path (including its name), node-group data-block, and internal property must match. Visible
socket names alone are never used for matching. An object that does not contain a matching property
is skipped. Shared data-blocks are changed only once.

String, pointer, and collection properties are intentionally excluded because they do not have a
generally useful, type-derived randomization rule.

## Development check

For live development, the folder containing this repository must be one level below a local
extension repository (a directory symlink is also supported):

```text
local_extensions/
└── randomize_value/
    ├── blender_manifest.toml
    ├── __init__.py
    └── randomize_core.py
```

After changing source files, use **Blender > System > Reload Scripts**, toggle the extension off
and on, or restart Blender. Source edits are not loaded automatically.

## Tests

The randomization core has no Blender dependency:

```powershell
python -m unittest discover -s tests -v
```

## Release

Releases are created automatically when a semantic version tag is pushed. Update both
`blender_manifest.toml` and `bl_info`, commit the change, then push a matching tag:

```powershell
git tag v0.7.1
git push origin v0.7.1
```

The release workflow verifies that the tag and both source versions match, builds the extension
ZIP from the manifest's `[build].paths`, and attaches it to a GitHub Release with generated notes.
