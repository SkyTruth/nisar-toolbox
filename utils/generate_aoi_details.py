import geopandas as gpd
from shapely.geometry import Point

# Generate an AOI in the format accepted by utils/variables.py SEARCH_AOIS


def define_aoi_from_bounds():
    ll_coordinate = input("Define lower left coord (min lon, min lat): ").replace(
        " ", ""
    )
    ur_coordinate = input("Define upper right coord (max lon, max lat): ").replace(
        " ", ""
    )
    return f"{ll_coordinate},{ur_coordinate}"


def define_aoi_from_point():
    point = input("Define center point (lon, lat): ").replace(" ", "")
    lon, lat = (float(v) for v in point.split(","))
    buffer_km = float(input("Buffer distance from point (km): "))

    # Point in WGS84, reprojected to its local UTM zone so the buffer is in metres
    gdf = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    utm_crs = gdf.estimate_utm_crs()
    buffered = gdf.to_crs(utm_crs).buffer(buffer_km * 1000, cap_style="square")

    # Back to lon/lat and take the bounding box
    min_lon, min_lat, max_lon, max_lat = buffered.to_crs(
        "EPSG:4326"
    ).total_bounds.round(6)
    return f"{min_lon},{min_lat},{max_lon},{max_lat}"


aoi_name = input("Descriptive AOI Name:  ").strip().lower().replace(" ", "-")

method = input("Define AOI from (1) bounds or (2) point + buffer? [1/2]: ").strip()
if method == "2":
    bbox = define_aoi_from_point()
else:
    bbox = define_aoi_from_bounds()

print("\nAdd this to SEARCH_AOIS in utils/variables.py:\n")
print(f'    "{aoi_name}": {{"bbox": "{bbox}"}},')
