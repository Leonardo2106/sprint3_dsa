"""Coleta e prepara dados reais de vegetação junto à SP-348.

O módulo deliberadamente usa somente a biblioteca padrão: assim a etapa de
aquisição e construção do dataset pode ser executada antes da instalação das
bibliotecas de visualização usadas no notebook e no dashboard.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
METADATA_DIR = ROOT / "metadata"

BBOX = (-23.25, -47.25, -22.82, -46.80)  # sul, oeste, norte, leste
MAX_DISTANCE_M = 500.0
EARTH_RADIUS_M = 6_371_008.8
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

ROAD_QUERY = """[out:json][timeout:90];
way[highway][ref~"SP-348"]({bbox});
out tags geom;"""

VEGETATION_QUERY = """[out:json][timeout:180][maxsize:268435456];
(
  way[natural~"^(wood|scrub|grassland)$"]({bbox});
  relation[natural~"^(wood|scrub|grassland)$"]({bbox});
  way[landuse~"^(forest|grass|meadow)$"]({bbox});
  relation[landuse~"^(forest|grass|meadow)$"]({bbox});
);
out tags geom;"""


@dataclass(frozen=True)
class VegetationPart:
    osm_type: str
    osm_id: int
    vegetation_type: str
    points: tuple[tuple[float, float], ...]  # latitude, longitude
    bbox: tuple[float, float, float, float]


def bbox_string() -> str:
    return ",".join(str(value) for value in BBOX)


def download_overpass(query: str, destination: Path) -> str:
    """Consulta uma instância Overpass e grava a resposta JSON compactada."""
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "User-Agent": "FIAP-DSA3-vegetation-monitoring/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                raw = response.read()
            parsed = json.loads(raw)
            if "elements" not in parsed:
                raise ValueError("Resposta da Overpass sem o campo 'elements'.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(destination, "wt", encoding="utf-8") as handle:
                json.dump(parsed, handle, ensure_ascii=False)
            return endpoint
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(2)
    raise RuntimeError(f"Nenhuma instância Overpass respondeu: {last_error}")


def load_json_gz(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def ensure_raw_data(refresh: bool) -> tuple[dict, dict, dict[str, str]]:
    road_path = RAW_DIR / "sp348_roads.json.gz"
    vegetation_path = RAW_DIR / "sp348_vegetation.json.gz"
    endpoints: dict[str, str] = {}
    if refresh or not road_path.exists():
        endpoints["roads"] = download_overpass(
            ROAD_QUERY.format(bbox=bbox_string()), road_path
        )
    else:
        endpoints["roads"] = "cache local"
    if refresh or not vegetation_path.exists():
        endpoints["vegetation"] = download_overpass(
            VEGETATION_QUERY.format(bbox=bbox_string()), vegetation_path
        )
    else:
        endpoints["vegetation"] = "cache local"
    return load_json_gz(road_path), load_json_gz(vegetation_path), endpoints


def in_bbox(latitude: float, longitude: float) -> bool:
    south, west, north, east = BBOX
    return south <= latitude <= north and west <= longitude <= east


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def to_local_xy(
    point: tuple[float, float], origin: tuple[float, float]
) -> tuple[float, float]:
    """Projeção equiretangular local, suficiente para distâncias subquilométricas."""
    lat, lon = point
    origin_lat, origin_lon = origin
    x = math.radians(lon - origin_lon) * EARTH_RADIUS_M * math.cos(
        math.radians(origin_lat)
    )
    y = math.radians(lat - origin_lat) * EARTH_RADIUS_M
    return x, y


def point_segment_distance(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    px, py = to_local_xy(point, point)
    ax, ay = to_local_xy(a, point)
    bx, by = to_local_xy(b, point)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    factor = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    nearest_x, nearest_y = ax + factor * dx, ay + factor * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def point_in_polygon(
    point: tuple[float, float], polygon: Sequence[tuple[float, float]]
) -> bool:
    """Teste ray casting; longitude funciona como x e latitude como y."""
    y, x = point
    inside = False
    previous_y, previous_x = polygon[-1]
    for current_y, current_x in polygon:
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            boundary_x = (previous_x - current_x) * (y - current_y) / (
                previous_y - current_y
            ) + current_x
            if x < boundary_x:
                inside = not inside
        previous_y, previous_x = current_y, current_x
    return inside


def distance_to_part(point: tuple[float, float], part: VegetationPart) -> float:
    points = part.points
    if len(points) >= 4 and points[0] == points[-1] and point_in_polygon(point, points):
        return 0.0
    return min(
        point_segment_distance(point, a, b)
        for a, b in zip(points, points[1:])
    )


def geometry_points(geometry: Iterable[dict]) -> tuple[tuple[float, float], ...]:
    return tuple(
        (float(point["lat"]), float(point["lon"]))
        for point in geometry
        if "lat" in point and "lon" in point
    )


def vegetation_parts(data: dict) -> list[VegetationPart]:
    parts: list[VegetationPart] = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        vegetation_type = tags.get("natural") or tags.get("landuse")
        geometries: list[Iterable[dict]] = []
        if element.get("geometry"):
            geometries.append(element["geometry"])
        for member in element.get("members", []):
            if member.get("role") == "outer" and member.get("geometry"):
                geometries.append(member["geometry"])
        for geometry in geometries:
            points = geometry_points(geometry)
            if len(points) < 2:
                continue
            latitudes = [point[0] for point in points]
            longitudes = [point[1] for point in points]
            bounds = (
                min(latitudes),
                min(longitudes),
                max(latitudes),
                max(longitudes),
            )
            if not (
                bounds[2] < BBOX[0]
                or bounds[0] > BBOX[2]
                or bounds[3] < BBOX[1]
                or bounds[1] > BBOX[3]
            ):
                parts.append(
                    VegetationPart(
                        osm_type=element["type"],
                        osm_id=int(element["id"]),
                        vegetation_type=str(vegetation_type),
                        points=points,
                        bbox=bounds,
                    )
                )
    return parts


def grid_key(latitude: float, longitude: float, cell_size: float = 0.01) -> tuple[int, int]:
    return math.floor(latitude / cell_size), math.floor(longitude / cell_size)


def build_spatial_index(parts: Sequence[VegetationPart]) -> dict[tuple[int, int], set[int]]:
    """Indexa caixas expandidas em 500 m para reduzir comparações de distância."""
    index: dict[tuple[int, int], set[int]] = defaultdict(set)
    latitude_margin = MAX_DISTANCE_M / 111_320
    mean_latitude = (BBOX[0] + BBOX[2]) / 2
    longitude_margin = MAX_DISTANCE_M / (111_320 * math.cos(math.radians(mean_latitude)))
    for part_index, part in enumerate(parts):
        south, west, north, east = part.bbox
        min_row, min_col = grid_key(south - latitude_margin, west - longitude_margin)
        max_row, max_col = grid_key(north + latitude_margin, east + longitude_margin)
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                index[(row, column)].add(part_index)
    return index


def nearest_vegetation(
    midpoint: tuple[float, float],
    parts: Sequence[VegetationPart],
    index: dict[tuple[int, int], set[int]],
) -> tuple[float, VegetationPart | None]:
    candidate_indices = index.get(grid_key(*midpoint), set())
    nearest_distance = MAX_DISTANCE_M
    nearest_part: VegetationPart | None = None
    for part_index in candidate_indices:
        part = parts[part_index]
        distance = distance_to_part(midpoint, part)
        if distance < nearest_distance:
            nearest_distance, nearest_part = distance, part
    return nearest_distance, nearest_part


def parse_speed(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    return int(digits) if digits else None


def label_priority(distance: float, vegetation_type: str | None) -> tuple[float, str]:
    proximity_score = max(0.0, 1 - min(distance, 300.0) / 300.0) * 80
    type_score = {
        "scrub": 20,
        "wood": 15,
        "forest": 15,
        "grassland": 10,
        "meadow": 10,
        "grass": 5,
    }.get(vegetation_type or "", 0)
    score = round(min(100.0, proximity_score + type_score), 1)
    priority = "alta" if score >= 70 else "media" if score >= 40 else "baixa"
    return score, priority


def build_rows(roads: dict, vegetation: dict) -> tuple[list[dict], list[VegetationPart]]:
    parts = vegetation_parts(vegetation)
    index = build_spatial_index(parts)
    rows: list[dict] = []
    row_id = 1
    for way in roads.get("elements", []):
        tags = way.get("tags", {})
        points = geometry_points(way.get("geometry", []))
        for start, end in zip(points, points[1:]):
            midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
            if not in_bbox(*midpoint):
                continue
            length = haversine_m(start, end)
            distance, nearest = nearest_vegetation(midpoint, parts, index)
            vegetation_type = nearest.vegetation_type if nearest else None
            score, priority = label_priority(distance, vegetation_type)
            rows.append(
                {
                    "segmento_id": row_id,
                    "osm_via_id": way["id"],
                    "rodovia": tags.get("ref", "SP-348"),
                    "nome_via": tags.get("name", ""),
                    "sentido_osm": tags.get("oneway", ""),
                    "faixas": tags.get("lanes", ""),
                    "velocidade_max_kmh": parse_speed(tags.get("maxspeed")) or "",
                    "latitude": round(midpoint[0], 7),
                    "longitude": round(midpoint[1], 7),
                    "comprimento_segmento_m": round(length, 1),
                    "distancia_vegetacao_m": round(distance, 1),
                    "tipo_vegetacao": vegetation_type or "sem_feicao_em_500m",
                    "osm_vegetacao_tipo": nearest.osm_type if nearest else "",
                    "osm_vegetacao_id": nearest.osm_id if nearest else "",
                    "score_prioridade": score,
                    "prioridade_inspecao": priority,
                }
            )
            row_id += 1
    if not rows:
        raise ValueError("Nenhum segmento da SP-348 foi encontrado dentro do recorte.")
    return rows, parts


def write_outputs(
    rows: list[dict],
    parts: Sequence[VegetationPart],
    roads: dict,
    vegetation: dict,
    endpoints: dict[str, str],
) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "segmentos_sp348.csv"
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    metadata = {
        "projeto": "Monitoramento de vegetação na SP-348",
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "fonte": "OpenStreetMap via Overpass API",
        "licenca": "ODbL 1.0",
        "bbox_sul_oeste_norte_leste": BBOX,
        "endpoints_nesta_execucao": endpoints,
        "timestamp_osm_rodovias": roads.get("osm3s", {}).get("timestamp_osm_base"),
        "timestamp_osm_vegetacao": vegetation.get("osm3s", {}).get("timestamp_osm_base"),
        "quantidade_elementos_rodovias_brutos": len(roads.get("elements", [])),
        "quantidade_elementos_vegetacao_brutos": len(vegetation.get("elements", [])),
        "quantidade_partes_vegetacao_processadas": len(parts),
        "quantidade_segmentos_dataset": len(rows),
        "distribuicao_prioridade": dict(Counter(row["prioridade_inspecao"] for row in rows)),
        "consultas_overpass": {
            "rodovias": ROAD_QUERY.format(bbox=bbox_string()),
            "vegetacao": VEGETATION_QUERY.format(bbox=bbox_string()),
        },
        "rotulagem": {
            "proximidade": "80 * max(0, 1 - distancia_m / 300)",
            "peso_tipo": {
                "scrub": 20,
                "wood/forest": 15,
                "grassland/meadow": 10,
                "grass": 5,
            },
            "classes": {"alta": ">= 70", "media": ">= 40 e < 70", "baixa": "< 40"},
        },
    }
    with (METADATA_DIR / "dataset_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignora o cache e consulta novamente a Overpass API.",
    )
    args = parser.parse_args()
    roads, vegetation, endpoints = ensure_raw_data(args.refresh)
    rows, parts = build_rows(roads, vegetation)
    write_outputs(rows, parts, roads, vegetation, endpoints)
    distribution = Counter(row["prioridade_inspecao"] for row in rows)
    print(f"Dataset criado: {PROCESSED_DIR / 'segmentos_sp348.csv'}")
    print(f"Segmentos: {len(rows)} | prioridades: {dict(distribution)}")


if __name__ == "__main__":
    main()

