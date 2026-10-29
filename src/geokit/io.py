"""Functions for reading and writing geographic data."""

from io import BytesIO

import geopandas as gpd
import requests


def read_wfs(
    url,
    layer,
    bbox=None,
    crs="EPSG:4326",
    bbox_crs=None,
    auth=None,
    version="2.0.0",
    timeout=60,
):
    """Read features from a WFS service into a GeoDataFrame.

    Parameters
    ----------
    url : str
        WFS service endpoint.
    layer : str
        Name of the requested feature type.
    bbox : tuple, optional
        Bounding box (minx, miny, maxx, maxy).
    crs : str
        Requested output coordinate system.
    bbox_crs : str, optional
        Coordinate system of bbox. Defaults to crs.
    auth : tuple or requests.auth.AuthBase, optional
        Authentication credentials.
    version : str
        WFS protocol version.
    timeout : int or tuple
        HTTP request timeout in seconds.

    Returns
    -------
    geopandas.GeoDataFrame
        Retrieved geographic features.
    """

    params = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeNames": layer,
        "outputFormat": "application/json",
        "srsName": crs,
    }

    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError("bbox must contain (minx, miny, maxx, maxy)")

        minx, miny, maxx, maxy = bbox

        if minx >= maxx or miny >= maxy:
            raise ValueError("Invalid bbox coordinates")

        bbox_crs = bbox_crs or crs
        params["bbox"] = f"{minx},{miny},{maxx},{maxy},{bbox_crs}"

    response = requests.get(url, params=params, auth=auth, timeout=timeout)
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise ValueError("WFS response is not valid GeoJSON") from exc

    if data.get("type") != "FeatureCollection":
        raise ValueError(
            f"WFS did not return a GeoJSON FeatureCollection: {data.get('type')}"
        )

    return gpd.read_file(BytesIO(response.content))
