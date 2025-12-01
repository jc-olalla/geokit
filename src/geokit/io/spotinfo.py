# src/geokit/io/closed/spotinfo.py
from __future__ import annotations
from typing import Any, Dict, Optional

import geopandas as gpd
import requests

from geokit.config import SPOTINFO
import pandas as pd

from .base import build_url, create_basic_auth_session


def create_session() -> requests.Session:
    """
    Spotinfo-specific session, built on generic basic-auth helper.
    """
    return create_basic_auth_session(
        username=SPOTINFO.username,
        password=SPOTINFO.password,
        # you can add Spotinfo-specific headers here if needed:
        # headers={"User-Agent": "geokit/1.0"},
    )


def spotinfo_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    url = build_url(SPOTINFO.base_url, path)
    session = create_session()
    resp = session.get(url, params=params)
    resp.raise_for_status()
    return resp


def fetch_table(path: str, params=None) -> pd.DataFrame:
    data = spotinfo_get(path, params=params).json()
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    return pd.DataFrame(data)


def fetch_geodata(
    path: str,
    params=None,
    geometry_column="geometry",
    crs="EPSG:28992",
) -> gpd.GeoDataFrame:
    # implement mapping from Spotinfo’s JSON to shapely geometries here
    raise NotImplementedError
