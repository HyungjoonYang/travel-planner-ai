"""Resolve place images via Wikimedia Commons (free, no API key)."""

import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)

# Category → fallback emoji for places without Wikipedia images
_CATEGORY_ICONS = {
    "food": "🍜", "restaurant": "🍜", "cafe": "☕", "bar": "🍺",
    "sightseeing": "🏛️", "museum": "🏛️", "temple": "⛩️", "shrine": "⛩️",
    "park": "🌳", "garden": "🌳", "nature": "🌿",
    "shopping": "🛍️", "market": "🛍️",
    "hotel": "🏨", "accommodation": "🏨",
    "transport": "🚇", "station": "🚇",
    "beach": "🏖️", "island": "🏝️",
}


def _fallback_icon(category: str) -> str:
    cat = category.lower()
    for key, icon in _CATEGORY_ICONS.items():
        if key in cat:
            return icon
    return "📍"


def resolve_photo_url(place_name: str, category: str = "") -> dict:
    """Look up a Wikipedia thumbnail for a place.

    Returns {"photo_url": "https://..." or "", "fallback_icon": "🏛️"}.
    """
    fallback = _fallback_icon(category)
    try:
        encoded = urllib.parse.quote(place_name)
        url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=query&titles={encoded}&prop=pageimages"
            f"&format=json&pithumbsize=400&redirects=1"
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            thumb = page.get("thumbnail", {}).get("source")
            if thumb:
                return {"photo_url": thumb, "fallback_icon": fallback}
    except Exception as exc:
        logger.debug("image_resolver: %s — %s", place_name, exc)
    return {"photo_url": "", "fallback_icon": fallback}


def generate_google_maps_url(name: str, address: str = "") -> str:
    """Generate a Google Maps search deep link."""
    query = f"{name} {address}".strip()
    return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(query)}"
