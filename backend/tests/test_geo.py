import math

import pytest

from app.errors import InvalidRequestError
from app.geo import BBox, dedupe_parks, is_valid_coordinate
from tests.conftest import make_park


class TestIsValidCoordinate:
    @pytest.mark.parametrize("lat,lng", [(40.7, -73.9), ("40.7", "-73.9"), (-90, 180), (90, -180)])
    def test_accepts_valid(self, lat, lng):
        assert is_valid_coordinate(lat, lng)

    @pytest.mark.parametrize(
        "lat,lng",
        [(None, 1), (1, None), ("abc", 1), (91, 0), (0, 181), (math.nan, 1), (1, math.inf), (0, 0), (True, 1), ([], 1)],
    )
    def test_rejects_malformed(self, lat, lng):
        assert not is_valid_coordinate(lat, lng)


class TestBBox:
    def test_create_valid(self):
        box = BBox.create(30, -98, 31, -97)
        assert box.lat_span == 1 and box.lng_span == 1
        assert box.center == (30.5, -97.5)

    @pytest.mark.parametrize(
        "args",
        [(31, -98, 30, -97), (30, -97, 31, -98), (30, -98, 30, -97), (-91, 0, 0, 1), (0, -181, 1, 0), (math.nan, 0, 1, 1)],
    )
    def test_create_invalid(self, args):
        with pytest.raises(InvalidRequestError):
            BBox.create(*args)

    def test_ensure_max_span(self):
        BBox.create(30, -98, 30.5, -97.5).ensure_max_span(1.0)
        with pytest.raises(InvalidRequestError, match="too large"):
            BBox.create(30, -98, 32, -97.5).ensure_max_span(1.0)

    def test_clamp_to_span_keeps_center(self):
        box = BBox.create(20, -110, 40, -90).clamp_to_span(1.0)
        assert box.lat_span == pytest.approx(1.0) and box.lng_span == pytest.approx(1.0)
        assert box.center == pytest.approx((30, -100))

    def test_snapped_expands_outward_and_is_stable_for_small_pans(self):
        a = BBox.create(30.2612, -97.7488, 30.2987, -97.7011).snapped(0.01)
        b = BBox.create(30.2631, -97.7470, 30.2999, -97.7003).snapped(0.01)
        assert a == b
        assert a.south <= 30.2612 and a.north >= 30.2987 and a.west <= -97.7488 and a.east >= -97.7011

    def test_snapped_respects_world_limits(self):
        box = BBox.create(89.995, 179.991, 90, 180).snapped(0.01)
        assert box.north <= 90 and box.east <= 180

    def test_contains_edges(self):
        box = BBox.create(30, -98, 31, -97)
        assert box.contains(30, -98) and box.contains(31, -97)
        assert not box.contains(31.0001, -97.5)


class TestDedupe:
    def test_removes_same_id_keeping_richer(self):
        poor = make_park("osm-way-1")
        rich = make_park("osm-way-1", description="Nice", hours="24/7")
        assert dedupe_parks([poor, rich]) == [rich]

    def test_removes_same_name_nearby(self):
        node = make_park("osm-node-1", "Zilker Park", 30.2669, -97.7729)
        way = make_park("osm-way-2", "zilker park", 30.2670, -97.7730, hours="5 AM - 10 PM")
        result = dedupe_parks([node, way])
        assert len(result) == 1 and result[0].id == "osm-way-2"

    def test_keeps_same_name_far_apart(self):
        a = make_park("osm-way-1", "Central Park", 40.78, -73.96)
        b = make_park("osm-way-2", "Central Park", 30.27, -97.74)
        assert len(dedupe_parks([a, b])) == 2

    def test_empty(self):
        assert dedupe_parks([]) == []
