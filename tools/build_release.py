"""Build a Blender extension ZIP from blender_manifest.toml."""

from __future__ import annotations

import argparse
import ast
import os
import re
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "blender_manifest.toml"
SEMVER_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def addon_version() -> str:
    module = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "bl_info" for target in statement.targets):
            continue
        bl_info = ast.literal_eval(statement.value)
        return ".".join(str(part) for part in bl_info["version"])
    raise ValueError("bl_info version was not found in __init__.py")


def load_manifest() -> dict:
    with MANIFEST_PATH.open("rb") as manifest_file:
        return tomllib.load(manifest_file)


def validate_versions(tag: str, manifest: dict) -> str:
    tag_version = tag[1:] if tag.startswith("v") else tag
    if SEMVER_PATTERN.fullmatch(tag_version) is None:
        raise ValueError(f"Release tag must use vMAJOR.MINOR.PATCH, got {tag!r}")

    manifest_version = manifest["version"]
    python_version = addon_version()
    if tag_version != manifest_version or tag_version != python_version:
        raise ValueError(
            "Version mismatch: "
            f"tag={tag_version}, manifest={manifest_version}, bl_info={python_version}"
        )
    return tag_version


def package_paths(manifest: dict) -> list[tuple[Path, str]]:
    relative_paths = ["blender_manifest.toml", *manifest.get("build", {}).get("paths", [])]
    result: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for relative_path in relative_paths:
        archive_path = Path(relative_path).as_posix()
        if archive_path in seen:
            continue
        source_path = (ROOT / relative_path).resolve()
        if not source_path.is_relative_to(ROOT) or not source_path.is_file():
            raise ValueError(f"Invalid release file: {relative_path!r}")
        seen.add(archive_path)
        result.append((source_path, archive_path))
    return result


def write_zip(output_path: Path, files: list[tuple[Path, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source_path, archive_path in files:
            info = zipfile.ZipInfo(archive_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source_path.read_bytes())


def set_github_output(name: str, value: str) -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    version = validate_versions(args.tag, manifest)
    files = package_paths(manifest)
    package = args.output_dir / f"{manifest['id']}-{version}.zip"

    if not args.check_only:
        write_zip(package, files)

    set_github_output("package", package.as_posix())
    set_github_output("version", version)
    print(f"Validated release {version}" if args.check_only else f"Created {package}")


if __name__ == "__main__":
    main()
