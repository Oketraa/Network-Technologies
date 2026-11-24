"""Resolve addresses through Nominatim and road routes through OSRM."""

from functools import lru_cache
from math import ceil, isfinite
import json
import os
import re
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .common import InputError

ROUTER = os.environ.get(
    "ROBOTAXI_ROUTER_URL", "https://routing.openstreetmap.de/routed-car/route/v1/driving"
).rstrip("/")
GEOCODER = os.environ.get("ROBOTAXI_GEOCODER_URL", "https://nominatim.openstreetmap.org").rstrip("/")
_route_lock = Lock()
_last_request = float("-inf")
_address_lock = Lock()
_last_lookup = float("-inf")
HOUSE_NUMBER = r"\d+[а-яa-z]?(?:[/\-к]\d+[а-яa-z]?)?"


def point(raw):
    try:
        lat, lng = (round(float(value), 6) for value in raw.split(","))
        if not -85 <= lat <= 85 or not -180 <= lng <= 180:
            raise ValueError
        return lat, lng
    except (TypeError, ValueError) as exc:
        raise InputError("Укажите точку посадки и пункт назначения на карте.") from exc


def point_label(coords):
    return ", ".join(f"{value:.6f}" for value in coords)


@lru_cache(maxsize=256)
def _query_address(service, parameters):
    global _last_lookup
    query = urlencode({"format": "jsonv2", "addressdetails": 1, "accept-language": "ru", **dict(parameters)})
    sleep(max(0, 1 - (monotonic() - _last_lookup)))
    _last_lookup = monotonic()
    request = Request(
        f"{GEOCODER}/{service}?{query}",
        headers={"User-Agent": "RoboTaxi/1.0 (interactive address lookup)", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read(128_000))
    except HTTPError as exc:
        if service == "reverse" and exc.code == 404:
            return None
        raise InputError("Сервис адресов временно недоступен. Попробуйте ещё раз или выберите точки на карте.") from exc
    except (OSError, ValueError) as exc:
        raise InputError("Сервис адресов временно недоступен. Попробуйте ещё раз или выберите точки на карте.") from exc


def _address_query(service, **parameters):
    # Share the public geocoder's limit and cache across search and reverse lookup.
    with _address_lock:
        return _query_address(service, tuple(parameters.items()))


def address_label(result):
    address = result.get("address") or {}
    street = next((address[field] for field in (
        "road", "pedestrian", "residential", "living_street", "square", "footway",
    ) if address.get(field)), "")
    if not street:
        return result.get("name", "")
    city = next((address[field] for field in ("city", "town", "village") if address.get(field)), "")
    return ", ".join(part for part in (city, street, address.get("house_number", "")) if part)


def reverse_address(coords):
    result = _address_query("reverse", lat=coords[0], lon=coords[1], zoom=18)
    return address_label(result) if isinstance(result, dict) else ""


def resolve_place(label, raw_point):
    if raw_point:
        coords = point(raw_point)
        if not label:
            try:
                label = reverse_address(coords)
            except InputError:
                # Coordinates are sufficient for routing if the address service is down.
                pass
        return coords, label or point_label(coords)
    if not label:
        raise InputError("Укажите адрес или выберите точку на карте для начала и конца маршрута.")
    query = " ".join(label.split())
    house = re.search(rf"(?:,|\s)(?:дом\s+|д\.\s*)?({HOUSE_NUMBER})$", query, re.IGNORECASE)
    if not house:
        house = re.match(rf"({HOUSE_NUMBER})\s*,", query, re.IGNORECASE)
    matches = _address_query(
        "search", q=query, limit=5 if house else 1, countrycodes="ru", viewbox="55.85,54.83,56.12,54.65",
    )
    if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
        raise InputError(f"Адрес «{label}» не найден. Проверьте город, улицу и номер дома.")
    if house:
        number = house[1]
        result = next((match for match in matches
                       if (match.get("address") or {}).get("house_number", "").casefold() == number.casefold()), None)
        if result is None:
            raise InputError(f"Дом № {number} по этому адресу не найден. Уточните адрес или выберите точку на карте.")
    else:
        result = matches[0]
    coords = point(f"{result.get('lat', '')},{result.get('lon', '')}")
    return coords, address_label(result) or label


def _fetch_route(url):
    global _last_request
    with _route_lock:
        # Keep interactive requests to the shared public endpoint at most one per second.
        sleep(max(0, 1 - (monotonic() - _last_request)))
        _last_request = monotonic()
        request = Request(url, headers={"User-Agent": "RoboTaxi/1.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                return json.loads(response.read(512_000))
        except HTTPError as exc:
            if exc.code == 400:
                raise InputError("Не удалось найти дорогу между точками. Выберите точки ближе к проезжей части.") from exc
            raise InputError("Сервис маршрутов временно недоступен. Повторите расчёт позже.") from exc
        except (OSError, URLError, ValueError) as exc:
            raise InputError("Сервис маршрутов временно недоступен. Повторите расчёт позже.") from exc


@lru_cache(maxsize=64)
def road_route(pickup, destination):
    if pickup == destination:
        raise InputError("Выберите разные точки для посадки и назначения.")
    locations = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in (pickup, destination))
    query = "overview=simplified&geometries=geojson&steps=false&radiuses=150;150"
    payload = _fetch_route(f"{ROUTER}/{locations}?{query}")
    if not isinstance(payload, dict) or payload.get("code") != "Ok":
        raise InputError("Не удалось найти дорогу между выбранными точками.")
    try:
        route = payload["routes"][0]
        meters, seconds = route["distance"], route["duration"]
        geometry = [(lat, lng) for lng, lat in route["geometry"]["coordinates"]]
        if not isfinite(meters) or not isfinite(seconds) or meters <= 0 or seconds <= 0 or len(geometry) < 2:
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise InputError("Сервис маршрутов не вернул маршрут для этих точек.") from exc
    return {
        "distance": max(1, round(meters / 100)),
        "duration": max(1, ceil(seconds / 60)),
        "map": {"pickup": pickup, "destination": destination, "geometry": geometry},
    }
