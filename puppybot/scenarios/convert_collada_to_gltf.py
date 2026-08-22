#!/usr/bin/env python3
"""Convert the Elephant Robotics adaptive-gripper COLLADA meshes to glTF.

The upstream Rhino exports contain millimetre geometry instanced through a
visual-scene matrix. RobotDreams renders glTF assets, so this converter bakes
each instance matrix into metre-space vertices and writes self-contained glTF
files using only the Python standard library.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import struct
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Iterable


COLLADA_NAMESPACE = "http://www.collada.org/2005/11/COLLADASchema"
NS = {"c": COLLADA_NAMESPACE}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory containing the upstream .dae files")
    parser.add_argument("destination", type=Path, help="directory for generated .gltf files")
    return parser.parse_args()


def floats(text: str | None) -> list[float]:
    if text is None:
        raise ValueError("missing COLLADA numeric data")
    return [float(value) for value in text.split()]


def matrix4(text: str | None) -> list[list[float]]:
    values = floats(text)
    if len(values) != 16:
        raise ValueError("COLLADA instance matrix must contain 16 numbers")
    return [values[index : index + 4] for index in range(0, 16, 4)]


def determinant3(matrix: list[list[float]]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def transform_position(matrix: list[list[float]], value: list[float], scale: float) -> tuple[float, float, float]:
    return tuple(
        scale
        * (
            matrix[row][0] * value[0]
            + matrix[row][1] * value[1]
            + matrix[row][2] * value[2]
            + matrix[row][3]
        )
        for row in range(3)
    )


def transform_normal(matrix: list[list[float]], value: list[float]) -> tuple[float, float, float]:
    transformed = [
        matrix[row][0] * value[0] + matrix[row][1] * value[1] + matrix[row][2] * value[2]
        for row in range(3)
    ]
    length = math.sqrt(sum(component * component for component in transformed))
    if length == 0.0:
        raise ValueError("COLLADA normal has zero length after transformation")
    return tuple(component / length for component in transformed)


def source_values(mesh: element_tree.Element) -> dict[str, list[list[float]]]:
    result: dict[str, list[list[float]]] = {}
    for source in mesh.findall("c:source", NS):
        source_id = source.attrib["id"]
        array = floats(source.findtext("c:float_array", namespaces=NS))
        accessor = source.find("c:technique_common/c:accessor", NS)
        if accessor is None:
            raise ValueError(f"source {source_id} has no accessor")
        stride = int(accessor.attrib.get("stride", "1"))
        result[source_id] = [array[index : index + stride] for index in range(0, len(array), stride)]
    return result


def geometry_instance_matrices(root: element_tree.Element) -> dict[str, list[list[float]]]:
    library_nodes = {
        node.attrib["id"]: node for node in root.findall("c:library_nodes/c:node", NS)
    }
    matrices: dict[str, list[list[float]]] = {}
    for node in root.findall("c:library_visual_scenes/c:visual_scene/c:node", NS):
        instance_node = node.find("c:instance_node", NS)
        if instance_node is None:
            continue
        definition = library_nodes[instance_node.attrib["url"].removeprefix("#")]
        instance_geometry = definition.find(".//c:instance_geometry", NS)
        if instance_geometry is None:
            continue
        geometry_id = instance_geometry.attrib["url"].removeprefix("#")
        matrices[geometry_id] = matrix4(node.findtext("c:matrix", namespaces=NS))
    return matrices


def triangle_vertices(
    mesh: element_tree.Element,
    matrix: list[list[float]],
    metre_scale: float,
) -> tuple[list[float], list[float]]:
    sources = source_values(mesh)
    vertices = mesh.find("c:vertices", NS)
    if vertices is None:
        raise ValueError("COLLADA mesh has no vertices element")
    position_input = vertices.find("c:input[@semantic='POSITION']", NS)
    if position_input is None:
        raise ValueError("COLLADA vertices have no POSITION input")
    position_source = position_input.attrib["source"].removeprefix("#")

    positions: list[float] = []
    normals: list[float] = []
    mirrored = determinant3(matrix) < 0.0
    for triangles in mesh.findall("c:triangles", NS):
        inputs = triangles.findall("c:input", NS)
        stride = max(int(value.attrib.get("offset", "0")) for value in inputs) + 1
        vertex_input = next(value for value in inputs if value.attrib["semantic"] == "VERTEX")
        normal_input = next(value for value in inputs if value.attrib["semantic"] == "NORMAL")
        vertex_offset = int(vertex_input.attrib.get("offset", "0"))
        normal_offset = int(normal_input.attrib.get("offset", "0"))
        normal_source = normal_input.attrib["source"].removeprefix("#")
        indices = [int(value) for value in triangles.findtext("c:p", default="", namespaces=NS).split()]
        corners = [indices[index : index + stride] for index in range(0, len(indices), stride)]
        if len(corners) % 3:
            raise ValueError("COLLADA triangles contain an incomplete face")
        for start in range(0, len(corners), 3):
            face = corners[start : start + 3]
            if mirrored:
                face[1], face[2] = face[2], face[1]
            for corner in face:
                positions.extend(
                    transform_position(matrix, sources[position_source][corner[vertex_offset]], metre_scale)
                )
                normals.extend(transform_normal(matrix, sources[normal_source][corner[normal_offset]]))
    return positions, normals


def aligned_extend(buffer: bytearray, values: Iterable[float]) -> tuple[int, int]:
    while len(buffer) % 4:
        buffer.append(0)
    offset = len(buffer)
    values = list(values)
    packed = struct.pack(f"<{len(values)}f", *values)
    buffer.extend(packed)
    return offset, len(packed)


def vector_bounds(values: list[float]) -> tuple[list[float], list[float]]:
    columns = [values[index::3] for index in range(3)]
    return [min(column) for column in columns], [max(column) for column in columns]


def convert(source: Path, destination: Path) -> None:
    root = element_tree.parse(source).getroot()
    unit = root.find("c:asset/c:unit", NS)
    metre_scale = float(unit.attrib.get("meter", "1")) if unit is not None else 1.0
    instance_matrices = geometry_instance_matrices(root)
    binary = bytearray()
    buffer_views = []
    accessors = []
    primitives = []

    for geometry in root.findall("c:library_geometries/c:geometry", NS):
        geometry_id = geometry.attrib["id"]
        matrix = instance_matrices.get(geometry_id)
        if matrix is None:
            raise ValueError(f"geometry {geometry_id} has no visual-scene instance")
        mesh = geometry.find("c:mesh", NS)
        if mesh is None:
            raise ValueError(f"geometry {geometry_id} has no mesh")
        positions, normals = triangle_vertices(mesh, matrix, metre_scale)
        if not positions:
            continue

        position_offset, position_length = aligned_extend(binary, positions)
        position_view = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": position_offset, "byteLength": position_length, "target": 34962}
        )
        position_min, position_max = vector_bounds(positions)
        position_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": 5126,
                "count": len(positions) // 3,
                "type": "VEC3",
                "min": position_min,
                "max": position_max,
            }
        )

        normal_offset, normal_length = aligned_extend(binary, normals)
        normal_view = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": normal_offset, "byteLength": normal_length, "target": 34962}
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view,
                "componentType": 5126,
                "count": len(normals) // 3,
                "type": "VEC3",
            }
        )
        primitives.append(
            {
                "attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor},
                "material": 0,
                "mode": 4,
            }
        )

    encoded = base64.b64encode(binary).decode("ascii")
    document = {
        "asset": {"version": "2.0", "generator": "PuppyBot COLLADA-to-glTF converter"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": source.stem}],
        "meshes": [{"name": source.stem, "primitives": primitives}],
        "materials": [
            {
                "name": "Adaptive gripper",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.62, 0.67, 0.72, 1.0],
                    "metallicFactor": 0.45,
                    "roughnessFactor": 0.36,
                },
            }
        ],
        "buffers": [{"byteLength": len(binary), "uri": f"data:application/octet-stream;base64,{encoded}"}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    arguments = parse_args()
    arguments.destination.mkdir(parents=True, exist_ok=True)
    sources = sorted(arguments.source.glob("*.dae"))
    if not sources:
        raise SystemExit(f"no .dae files found in {arguments.source}")
    for source in sources:
        destination = arguments.destination / f"{source.stem}.gltf"
        convert(source, destination)
        print(f"converted {source} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
