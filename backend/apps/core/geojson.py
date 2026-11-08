"""Minimal GeoJSON geometry validation (WGS84 Polygon / MultiPolygon).

PostGIS is deliberately not used in the MVP (OPEN_QUESTIONS Q11).
"""

from typing import Any

from django.core.exceptions import ValidationError

ALLOWED_TYPES = {"Polygon", "MultiPolygon"}


def _validate_position(position: Any) -> None:
    if not isinstance(position, list | tuple) or len(position) < 2:
        raise ValidationError("Position GeoJSON invalide.")
    lon, lat = position[0], position[1]
    for value in (lon, lat):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError("Coordonnée non numérique.")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValidationError("Coordonnées hors limites (longitude, latitude WGS84).")


def _validate_polygon(rings: Any) -> None:
    if not isinstance(rings, list) or not rings:
        raise ValidationError("Polygone vide.")
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValidationError("Un anneau doit contenir au moins 4 positions.")
        for position in ring:
            _validate_position(position)
        if list(ring[0][:2]) != list(ring[-1][:2]):
            raise ValidationError("Un anneau doit être fermé (première = dernière position).")


def validate_geometry(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError("La géométrie doit être un objet GeoJSON.")
    geometry_type = value.get("type")
    if geometry_type not in ALLOWED_TYPES:
        raise ValidationError("Type de géométrie accepté : Polygon ou MultiPolygon.")
    coordinates = value.get("coordinates")
    if geometry_type == "Polygon":
        _validate_polygon(coordinates)
    else:
        if not isinstance(coordinates, list) or not coordinates:
            raise ValidationError("MultiPolygon vide.")
        for polygon in coordinates:
            _validate_polygon(polygon)
