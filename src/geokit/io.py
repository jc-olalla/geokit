"""Functions for reading and writing geographic data."""

import inspect
import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import yaml
from matplotlib.figure import Figure

from geokit.spatial import subset_spatial, validate_boundary


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


def _resolve_writer(path, writer):
    """Select and validate the writer for the output path."""
    if writer is None:
        extension = path.suffix.lower()

        if extension == ".csv":

            def writer(obj, path, **kw):
                kw.setdefault("index", False)
                obj.to_csv(path, **kw)

        elif extension in {".gpkg", ".geojson", ".shp"}:

            def writer(obj, path, **kw):
                obj.to_file(path, **kw)

        elif extension in {".png", ".pdf", ".svg"}:

            def writer(obj, path, **kw):
                obj.savefig(path, **kw)

        else:
            raise ValueError(f"Unsupported output format: {extension}")

    if not callable(writer):
        raise TypeError("writer must be callable")

    return writer


def write(
    obj,
    path,
    metadata=None,
    script=None,
    project_root=None,
    writer=None,
    lineage=None,
    **kwargs,
):
    """
    Write an object to a file and create or update its metadata.

    Built-in formats:
        CSV (.csv):                  obj.to_csv()
        GIS (.gpkg, .geojson, .shp): obj.to_file()
        Figures (.png, .pdf, .svg):  obj.savefig()

    Other formats can be supported through a custom writer.

    Parameters
    ----------
    obj : object
        Object to write, such as a DataFrame, GeoDataFrame, or Figure.
    path : str or Path
        Output file path.
    metadata : dict, optional
        Descriptive metadata (e.g., title, description, author).
        Existing descriptive fields are preserved unless overwritten.
    script : str or Path, optional
        Generating script. Automatically detected if omitted.
    project_root : str or Path, optional
        Root directory used to make the script path relative.
        Defaults to the generating script's parent directory.
    writer : callable, optional
        Custom function with signature writer(obj, path, **kwargs).
        Overrides the built-in format selection.
    lineage : str or Path, optional
        Path to the lineage document, relative to the metadata file.
        Defaults to None when no lineage has been generated.
    **kwargs
        Additional arguments passed to the selected writer.

    Returns
    -------
    pathlib.Path
        Path to the written output.
    """
    path = Path(path)

    writer = _resolve_writer(path, writer)

    # Identify generating script
    script = Path(script or inspect.stack()[1].filename).resolve()
    project_root = Path(project_root).resolve() if project_root else script.parent
    script_relative = script.relative_to(project_root).as_posix()

    # Create output directory and write file
    path.parent.mkdir(parents=True, exist_ok=True)
    writer(obj, path, **kwargs)

    # TODO: Integrate automatic analytical provenance via @gk.trace.
    # Retrieve the lineage document associated with this output from
    # the current execution context (e.g., get_current_lineage(path)).
    # Explicit lineage takes precedence over automatically generated lineage.

    origin = {
        **(metadata or {}),
        "script": script_relative,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lineage": Path(lineage).as_posix() if lineage is not None else None,
    }

    meta_path = path.with_suffix(".meta.yml")
    meta_path.write_text(
        yaml.safe_dump({"origin": origin}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    return path
