import urllib.parse
from typing import Any
import aiohttp
from mcp_server.settings import Settings

settings = Settings()

async def check_street_view_metadata(
    session: aiohttp.ClientSession, address: str
) -> dict[str, Any]:
    url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {"location": address, "key": settings.gcp_api_key.get_secret_value()}
    async with session.get(url, params=params) as response:
        return await response.json()

def get_google_maps_link(address: str) -> str:
    encoded_address = urllib.parse.quote(address)
    return f"https://www.google.com/maps/search/?api=1&query={encoded_address}"

def get_street_view_link(metadata: dict[str, Any]) -> str | None:
    # Create a precise keyless Street View link using the Pano ID
    pano_id = metadata.get("pano_id")
    if pano_id:
        return f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano_id}"
    
    # Fallback to viewpoint if pano_id is missing
    location = metadata.get("location")
    if location:
        lat, lng = location.get("lat"), location.get("lng")
        if lat and lng:
            return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}"
    
    return None
