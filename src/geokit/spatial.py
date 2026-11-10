import re
import pandas as pd
import geopandas as gpd
from shapely.geometry.base import BaseGeometry


def validate_boundary(boundary, crs=None):
    """Validate a polygon boundary and return it as a GeoDataFrame."""

    # Standardize input
    if isinstance(boundary, gpd.GeoDataFrame):
        gdf = boundary.copy()

    elif isinstance(boundary, gpd.GeoSeries):
        gdf = gpd.GeoDataFrame(geometry=boundary.copy())

    elif isinstance(boundary, BaseGeometry):
        gdf = gpd.GeoDataFrame(geometry=[boundary], crs=crs)

    else:
        raise TypeError(
            "Boundary must be a GeoDataFrame, GeoSeries, or Shapely geometry"
        )

    # Validate CRS
    if gdf.crs is None:
        raise ValueError("Boundary has no CRS")

    # Remove empty geometries
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if gdf.empty:
        raise ValueError("Boundary contains no geometries")

    # Validate geometry types
    if not gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise TypeError("Boundary must contain only polygons or multipolygons")

    # Validate geometries
    if not gdf.geometry.is_valid.all():
        raise ValueError("Boundary contains invalid geometries")

    return gdf


def subset_spatial(data, boundary, method="intersects", clip=False):
    """Select features intersecting a boundary or whose centroids fall within it, optionally clipping."""

    # Ensure both datasets use the same CRS
    if data.crs is None:
        raise ValueError("Data has no CRS")

    boundary = validate_boundary(boundary).to_crs(data.crs)
    geometry = boundary.geometry.union_all()

    # Select features
    if method == "intersects":
        mask = data.intersects(geometry)

    elif method == "representative_point":
        points = data.geometry.representative_point()
        mask = points.within(geometry)

    elif method == "centroid":
        if data.geom_type.eq("Point").all():
            points = data.geometry
        else:
            if data.crs.is_geographic:
                raise ValueError(
                    "Centroid selection for non-point geometries requires a projected CRS"
                )
            points = data.geometry.centroid

        mask = points.within(geometry)

    else:
        raise ValueError(
            f"Unknown method '{method}'. Choose 'intersects' or 'centroid'."
        )

    result = data.loc[mask].copy()

    # Optionally clip geometries
    if clip:
        result = result.clip(geometry)

    return result


def _validate_aggregation(target, source, statistics, groupby, predicate):
    """Validate inputs for spatial aggregation."""

    if not isinstance(target, gpd.GeoDataFrame) or not isinstance(
        source, gpd.GeoDataFrame
    ):
        raise TypeError("target and source must be GeoDataFrames")

    if target.crs is None or source.crs is None:
        raise ValueError("Both GeoDataFrames must have a CRS")

    if not statistics:
        raise ValueError("At least one statistic must be provided")

    if predicate not in ("within", "intersects", "centroid"):
        raise ValueError(f"Unsupported predicate: {predicate}")

    operations = {"count", "sum", "mean", "median", "min", "max", "std"}

    for name, spec in statistics.items():
        if not isinstance(spec, tuple) or len(spec) != 2:
            raise ValueError(
                f"Invalid statistic '{name}': expected (column, operation)"
            )

        column, operation = spec

        if operation not in operations:
            raise ValueError(f"Unsupported operation: {operation}")

        if column is None and operation != "count":
            raise ValueError(f"Statistic '{name}' requires a source column")

        if column is not None and column not in source.columns:
            raise KeyError(f"Column '{column}' not found in source")

    if groupby is not None and groupby not in source.columns:
        raise KeyError(f"Column '{groupby}' not found in source")

    if set(statistics) & set(target.columns):
        raise ValueError("Statistic names must not overwrite existing target columns")

    if predicate not in ("within", "intersects", "centroid", "representative_point"):
        raise ValueError(f"Unsupported predicate: {predicate}")

    if (
        predicate == "centroid"
        and source.crs.is_geographic
        and not source.geom_type.eq("Point").all()
    ):
        raise ValueError(
            "Centroid aggregation of non-point geometries requires a projected CRS"
        )


def _prepare_spatial_join(source, predicate):
    """Prepare source geometries and predicate for spatial joining."""

    if predicate == "centroid":
        points = (
            source.geometry
            if source.geom_type.eq("Point").all()
            else source.geometry.centroid
        )
        source = source.set_geometry(points)
        predicate = "within"

    elif predicate == "representative_point":
        source = source.set_geometry(source.geometry.representative_point())
        predicate = "within"

    return source, predicate


def _calculate_statistics(joined, statistics, group_columns):
    """Calculate statistics for groups of spatially joined features."""

    grouped = joined.groupby(group_columns, observed=True, dropna=True)
    output = {}

    for name, (column, operation) in statistics.items():
        if column is None:
            output[name] = grouped.size()
        else:
            output[name] = grouped[column].agg(operation)

    return pd.DataFrame(output)


def _attach_statistics(result, aggregated, statistics, groupby=None):
    """Attach overall or categorical statistics to target features."""

    # Reshape categorical statistics into columns
    if groupby is not None:
        if aggregated.empty:
            return result

        aggregated = aggregated.unstack(groupby)

        column_operations = {}
        new_columns = []

        for name, category in aggregated.columns:
            suffix = re.sub(r"\W+", "_", str(category).strip().lower()).strip("_")
            column_name = f"{name}_{suffix}"

            new_columns.append(column_name)
            column_operations[column_name] = statistics[name][1]

        if len(new_columns) != len(set(new_columns)):
            raise ValueError("Different categories produced identical column names")

        aggregated.columns = new_columns

    else:
        column_operations = {
            name: operation for name, (_, operation) in statistics.items()
        }

    # Include all target units, including those without observations
    aggregated = aggregated.reindex(range(len(result)))

    # Fill missing values and enforce integer counts
    for column, operation in column_operations.items():
        if operation == "count":
            aggregated[column] = aggregated[column].fillna(0).astype(int)
        elif operation == "sum":
            aggregated[column] = aggregated[column].fillna(0)

    # Prevent overwriting existing attributes
    duplicates = set(aggregated.columns) & set(result.columns)
    if duplicates:
        raise ValueError(f"Output columns already exist: {duplicates}")

    # Attach statistics by row position, preserving the original target index
    for column in aggregated.columns:
        result[column] = aggregated[column].to_numpy()

    return result


def aggregate(target, source, statistics, groupby=None, predicate="within"):
    """
    Spatially aggregate source features to target geometries.

    Each source feature is assigned to target geometries according to the
    spatial predicate. Statistics are calculated for every target.

    When groupby is provided, both overall and category-specific statistics
    are calculated.

    Parameters
    ----------
    target : geopandas.GeoDataFrame
        Geometries defining aggregation units (e.g. buurten, gemeenten).

    source : geopandas.GeoDataFrame
        Features to aggregate (e.g. incidents, buildings, addresses).

    statistics : dict
        Dictionary defining output columns and aggregation operations.

        Format:
            {output_column: (source_column, operation)}

        Supported operations:
            "count", "sum", "mean", "median", "min", "max", "std"

        Counting:
            (None, "count")           # Number of source features
            ("oppervlakte", "count")  # Number of non-null oppervlakte values

        Examples:
            {
                "n_incidenten": (None, "count"),
                "mean_area": ("oppervlakte", "mean"),
                "total_area": ("oppervlakte", "sum"),
            }

    groupby : str, optional
        Source attribute used for categorical aggregation.

        When provided, calculates both overall statistics and statistics
        for each category.

        Category columns follow:
            {output_column}_{category}

        Spaces in category names are replaced with underscores.
        Missing categories are excluded from categorical statistics but
        included in overall statistics.

    predicate : str, default "within"
        Spatial relationship used to assign source features to targets.

        Supported values:
            "within"     - Source geometry lies entirely within target.
            "intersects" - Source geometry intersects target.
            "centroid"   - Source centroid lies within target.

        A source feature can be assigned to multiple targets if it satisfies
        the spatial relationship for more than one target.

    Returns
    -------
    geopandas.GeoDataFrame
        Copy of target with aggregated statistics added.

        Empty aggregation units receive:
            count, sum: 0
            mean, median, min, max, std: NaN

    Examples
    --------
    >>> aggregate(buurten, incidenten, {"n_incidenten": (None, "count")})

    >>> aggregate(
    ...     buurten,
    ...     incidenten,
    ...     {"n_incidenten": (None, "count")},
    ...     groupby="functie_1",
    ... )

    >>> aggregate(
    ...     gemeenten,
    ...     panden,
    ...     {
    ...         "n_panden": (None, "count"),
    ...         "mean_area": ("oppervlakte", "mean"),
    ...     },
    ...     predicate="centroid",
    ... )
    """

    # Validate inputs
    _validate_aggregation(target, source, statistics, groupby, predicate)

    # Prepare geometries
    result = target.copy()
    units = target[[target.geometry.name]].reset_index(drop=True)
    source = source.to_crs(target.crs)

    # Prepare spatial assignment
    source, predicate = _prepare_spatial_join(source, predicate)

    # Spatial join: adds index_right (only successful matches)
    joined = gpd.sjoin(source, units, how="inner", predicate=predicate)

    # Calculate statistics, optionally grouped by category
    overall = _calculate_statistics(joined, statistics, "index_right")
    result = _attach_statistics(result, overall, statistics)

    if groupby is not None:  # Categorical statistics
        categories = _calculate_statistics(joined, statistics, ["index_right", groupby])

        result = _attach_statistics(result, categories, statistics, groupby=groupby)

    return result
