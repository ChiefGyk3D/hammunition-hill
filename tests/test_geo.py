import math

import pytest

from hammunition_hill.geo import (
    GridError,
    bearing_deg,
    compass_point,
    distance_km,
    grid_to_latlon,
    latlon_to_grid,
    path,
)


def test_grid_to_latlon_returns_square_centre():
    """FN31pr is the classic reference square (Newington, CT).

    Hand-checked: field F/N -> -80/+40, square 3/1 -> -74/41, subsquare p/r ->
    -72.75/41.708, plus half a subsquare to reach the centre.
    """
    lat, lon = grid_to_latlon("FN31pr")
    assert lat == pytest.approx(41.729, abs=0.002)
    assert lon == pytest.approx(-72.708, abs=0.002)


@pytest.mark.parametrize("grid,lat,lon", [
    ("JJ00", 0.5, 0.0833),        # origin corner of the grid system
    ("IO91", 51.5, -1.0),         # London
    ("PM95", 35.5, 139.0),        # Tokyo
    ("QF56", -33.5, 151.0),       # Sydney
])
def test_four_character_grids(grid, lat, lon):
    got_lat, got_lon = grid_to_latlon(grid)
    assert got_lat == pytest.approx(lat, abs=0.6)
    assert got_lon == pytest.approx(lon, abs=1.1)


def test_two_character_grid_is_field_centre():
    lat, lon = grid_to_latlon("FN")
    assert (lat, lon) == (45.0, -70.0)


def test_roundtrip_through_grid_and_back():
    for grid in ("FN31pr", "IO91wm", "PM95ut", "QF56od", "JJ00aa"):
        lat, lon = grid_to_latlon(grid)
        assert latlon_to_grid(lat, lon, 6).upper() == grid.upper()


@pytest.mark.parametrize("bad", ["", "F", "ZZ99", "FN3", "FN31p", "12ab", "FN31pr99x"])
def test_malformed_grids_are_rejected(bad):
    with pytest.raises(GridError):
        grid_to_latlon(bad)


def test_grid_is_case_insensitive():
    assert grid_to_latlon("fn31PR") == grid_to_latlon("FN31pr")


def test_latlon_to_grid_handles_the_poles_and_dateline():
    """Clamping matters: an unclamped 180.0 would overflow past field R."""
    for lat, lon in ((90.0, 180.0), (-90.0, -180.0), (90.0, -180.0)):
        assert len(latlon_to_grid(lat, lon, 6)) == 6


def test_distance_new_york_to_london():
    km = distance_km(40.7128, -74.0060, 51.5074, -0.1278)
    assert km == pytest.approx(5570, rel=0.01)


def test_distance_is_symmetric():
    a = distance_km(40.0, -74.0, 51.0, 0.0)
    b = distance_km(51.0, 0.0, 40.0, -74.0)
    assert a == pytest.approx(b)


def test_distance_to_self_is_zero():
    assert distance_km(41.7, -72.7, 41.7, -72.7) == pytest.approx(0.0, abs=1e-9)


def test_antipodal_distance_is_half_the_circumference():
    km = distance_km(0.0, 0.0, 0.0, 180.0)
    assert km == pytest.approx(math.pi * 6371.0088, rel=1e-6)


def test_bearing_due_north_and_east():
    assert bearing_deg(0.0, 0.0, 10.0, 0.0) == pytest.approx(0.0, abs=0.01)
    assert bearing_deg(0.0, 0.0, 0.0, 10.0) == pytest.approx(90.0, abs=0.01)


def test_bearing_new_york_to_london_is_northeasterly():
    """The great-circle heading is well north of the rhumb line -- that is the point."""
    assert bearing_deg(40.7128, -74.0060, 51.5074, -0.1278) == pytest.approx(51.2, abs=1.0)


@pytest.mark.parametrize("deg,point", [(0, "N"), (45, "NE"), (90, "E"), (180, "S"), (350, "N")])
def test_compass_points(deg, point):
    assert compass_point(deg) == point


def test_path_bundles_short_and_long():
    result = path(41.7, -72.7, 51.5, -0.1)
    assert result["bearing_long"] == pytest.approx((result["bearing"] + 180) % 360, abs=0.1)
    assert result["miles"] < result["km"]
    assert result["compass"] == "NE"
