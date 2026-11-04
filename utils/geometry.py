from rasterio.warp import transform_bounds


def crop_pixels(bbox: list[float], pixel_size_m: float) -> int:
    """Approximate output pixels for a lon/lat bbox, measured in the UTM zone of its center (as NISAR grids are)."""
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
    west, south, east, north = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox)
    return round((east - west) / pixel_size_m) * round((north - south) / pixel_size_m)
