"""Functions for reading and writing geographic data."""

from io import BytesIO

import geopandas as gpd
import requests
import xml.etree.ElementTree as ET

import tomllib
from geokit.spatial import validate_boundary, subset_spatial


def read_wfs(
    url,
    layer,
    bbox=None,
    bbox_crs=None,
    crs=None,
    auth=None,
    version="2.0.0",
    timeout=60,
    filters=None,
):
    """Read a WFS layer into a GeoDataFrame, optionally filtering its features."""

    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": layer,
        "outputFormat": "application/json",
    }

    if crs is not None:
        params["srsName"] = crs

    if bbox is not None:
        if bbox_crs is None:
            raise ValueError("bbox_crs is required when providing a bbox")

        params["bbox"] = ",".join(map(str, [*bbox, bbox_crs]))

    response = requests.get(url, params=params, auth=auth, timeout=timeout)
    response.raise_for_status()

    gdf = gpd.read_file(BytesIO(response.content))

    if filters:
        gdf = filter_attributes(gdf, filters)

    return gdf


def read_wfs_within(
    url,
    layer,
    boundary,
    bbox_crs=None,
    crs=None,
    clip=False,
    auth=None,
    strategy="bbox",
    filters=None,
    subset_method="centroid",
):

    # 1. Prepare boundary
    boundary = validate_boundary(boundary)

    # Determine CRS
    info = get_wfs_layer_info(url, layer, auth=auth)
    bbox_crs = bbox_crs or info["default_crs"]
    crs = crs or info["default_crs"]

    # Transform boundary and calculate bounding box
    bbox = boundary.to_crs(bbox_crs).total_bounds

    # 2. Determine retrieval strategy
    # if strategy == "auto":
    #    strategy = select_retrieval_strategy(url, layer, boundary)

    # 3. Retrieve features
    if strategy == "bbox":
        bbox = boundary.total_bounds
        data = read_wfs(
            url,
            layer,
            bbox=bbox,
            bbox_crs=bbox_crs,
            crs=crs,
            auth=auth,
            filters=filters,
        )

        # elif strategy == "tiles":
        #    tiles = create_tiles(boundary)
        #
        #    data = []
        #    for tile in tiles:
        #        if tile.intersects(boundary):
        #            features = read_wfs(url, layer, bbox=tile.bounds, **kwargs)
        #            data.append(features)
        #
        #    data = combine_features(data)
        #
        # elif strategy == "adaptive":
        # data = read_wfs_adaptive(url, layer, boundary, **kwargs)

    # 4. Select features within the exact boundary
    data = subset_spatial(data, boundary, method=subset_method, clip=clip)

    # 5. Return
    return data


def filter_attributes(gdf, filters):
    """Filter a GeoDataFrame by attribute values."""

    for column, values in filters.items():
        if column not in gdf.columns:
            raise KeyError(f"Column '{column}' not found in GeoDataFrame")

        if isinstance(values, (list, tuple, set)):
            gdf = gdf[gdf[column].isin(values)]
        else:
            gdf = gdf[gdf[column] == values]

    return gdf.copy()


def get_service_auth(service_provider, secrets_file):
    """Retrieve service credentials from a TOML file."""

    with open(secrets_file, "rb") as f:
        secrets = tomllib.load(f)

    credentials = secrets[service_provider]
    return credentials["username"], credentials["password"]


def _get_wfs_capabilities(url, auth=None, version="2.0.0", timeout=60):
    """Retrieve and parse WFS GetCapabilities."""

    params = {
        "service": "WFS",
        "version": version,
        "request": "GetCapabilities",
    }

    response = requests.get(url, params=params, auth=auth, timeout=timeout)
    response.raise_for_status()

    root = ET.fromstring(response.content)

    if root.tag.split("}")[-1] != "WFS_Capabilities":
        raise ValueError("The service did not return a valid WFS capabilities document")

    return root


def list_wfs_layers(url, auth=None, search=None):
    """List WFS layers, optionally filtering by name or title."""

    root = _get_wfs_capabilities(url, auth=auth)
    ns = {"wfs": "http://www.opengis.net/wfs/2.0"}

    layers = []

    for feature in root.findall(".//wfs:FeatureType", ns):
        name = feature.findtext("wfs:Name", namespaces=ns)
        title = feature.findtext("wfs:Title", namespaces=ns)

        if not name:
            continue

        if search and search.lower() not in f"{name} {title or ''}".lower():
            continue

        layers.append({"name": name, "title": title})

    return layers


def get_wfs_layer_info(url, layer, auth=None):
    """Get metadata and supported coordinate systems for a WFS layer."""

    root = _get_wfs_capabilities(url, auth=auth)
    ns = {"wfs": "http://www.opengis.net/wfs/2.0"}

    for feature in root.findall(".//wfs:FeatureType", ns):
        name = feature.findtext("wfs:Name", namespaces=ns)

        if name != layer:
            continue

        default_crs = feature.findtext("wfs:DefaultCRS", namespaces=ns)
        other_crs = [element.text for element in feature.findall("wfs:OtherCRS", ns)]

        return {
            "name": name,
            "title": feature.findtext("wfs:Title", namespaces=ns),
            "default_crs": default_crs,
            "supported_crs": [default_crs] + other_crs,
        }

    raise ValueError(f"Layer '{layer}' not found in WFS service")
