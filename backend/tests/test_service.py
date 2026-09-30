import pytest

from app.errors import (
    CityNotFoundError,
    InvalidRequestError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
    UpstreamRateLimitedError,
    UpstreamTimeoutError,
)
from app.geo import BBox
from app.providers.base import GeocodedCity
from app.services.park_service import normalize_city_query
from tests.conftest import FakeGeocoder, FakePrimary, build_service, make_park

BROOKLYN_BBOX = BBox(40.57, -74.05, 40.74, -73.83)


@pytest.mark.parametrize("raw,expected", [("  Austin,   TX ", "Austin, TX"), ("Austin,", "Austin"), ("a\tb", "a b")])
def test_normalize_city_query(raw, expected):
    assert normalize_city_query(raw) == expected


async def test_search_by_city_happy_path(settings):
    primary = FakePrimary([make_park("osm-way-2", "Zeta Park"), make_park("osm-way-1", "Alpha Park", 30.3, -97.7)])
    service = build_service(settings, primary=primary)
    result = await service.search_by_city("Austin, TX")
    assert [p.name for p in result.parks] == ["Alpha Park", "Zeta Park"]  # sorted by name
    assert result.count == 2 and result.sources == ["openstreetmap"] and not result.degraded
    assert result.area is not None and result.area.label.startswith("Austin")


async def test_search_by_city_uses_cache(settings):
    geocoder, primary = FakeGeocoder(), FakePrimary()
    service = build_service(settings, geocoder, primary)
    await service.search_by_city("Austin, TX")
    await service.search_by_city("  austin,  tx ")
    assert len(geocoder.calls) == 1 and len(primary.bbox_calls) == 1


async def test_search_by_city_clamps_huge_area(settings):
    geocoder = FakeGeocoder(GeocodedCity(label="Texas", bbox=BBox(25.8, -106.6, 36.5, -93.5), lat=31, lng=-100))
    service = build_service(settings, geocoder)
    result = await service.search_by_city("Texas")
    assert any("very large" in w for w in result.warnings)
    box = result.area.bbox
    assert box.north - box.south <= settings.max_bbox_span_deg + 1e-9


async def test_city_not_found_falls_back_to_sample_match(settings):
    service = build_service(settings, FakeGeocoder(exc=CityNotFoundError("nope")))
    result = await service.search_by_city("Brooklyn")
    assert [p.id for p in result.parks] == ["prospect-park"]
    assert result.sources == ["sample"] and result.warnings


async def test_city_not_found_without_sample_match_raises(settings):
    service = build_service(settings, FakeGeocoder(exc=CityNotFoundError("nope")))
    with pytest.raises(CityNotFoundError):
        await service.search_by_city("Atlantis")


@pytest.mark.parametrize("exc", [UpstreamError("x"), UpstreamTimeoutError("x"), UpstreamRateLimitedError("x")])
async def test_geocoder_failure_degrades_to_sample(settings, exc):
    service = build_service(settings, FakeGeocoder(exc=exc))
    result = await service.search_by_city("Austin, TX")
    assert result.degraded and result.sources == ["sample"]
    assert [p.id for p in result.parks] == ["zilker-park"]


async def test_geocoder_failure_without_fallback_data_is_503_with_retry_after(settings):
    service = build_service(settings, FakeGeocoder(exc=UpstreamRateLimitedError("x", retry_after=12)))
    with pytest.raises(ServiceUnavailableError) as info:
        await service.search_by_city("Denver, CO")
    assert info.value.retry_after == 12


async def test_primary_failure_falls_back_to_sample_in_same_area(settings):
    geocoder = FakeGeocoder(GeocodedCity(label="Brooklyn", bbox=BROOKLYN_BBOX, lat=40.65, lng=-73.95))
    service = build_service(settings, geocoder, FakePrimary(exc=UpstreamTimeoutError("slow")))
    result = await service.search_by_city("Brooklyn, NY")
    assert result.degraded and [p.id for p in result.parks] == ["prospect-park"]
    assert any("sample data" in w for w in result.warnings)


async def test_primary_failure_without_sample_data_raises_503(settings):
    service = build_service(settings, primary=FakePrimary(exc=UpstreamError("500")))
    with pytest.raises(ServiceUnavailableError):
        await service.search_in_bounds(BBox(35, -80, 35.5, -79.5))


async def test_primary_failure_with_fallback_disabled_raises_503(settings):
    settings.enable_sample_fallback = False
    geocoder = FakeGeocoder(GeocodedCity(label="Brooklyn", bbox=BROOKLYN_BBOX, lat=40.65, lng=-73.95))
    service = build_service(settings, geocoder, FakePrimary(exc=UpstreamError("down")))
    with pytest.raises(ServiceUnavailableError):
        await service.search_by_city("Brooklyn")


async def test_failures_are_not_cached(settings):
    primary = FakePrimary(exc=UpstreamError("down"))
    service = build_service(settings, primary=primary)
    box = BBox(35, -80, 35.5, -79.5)
    with pytest.raises(ServiceUnavailableError):
        await service.search_in_bounds(box)
    primary.exc = None
    result = await service.search_in_bounds(box)
    assert result.count == 1


async def test_search_in_bounds_rejects_oversized_area(settings):
    service = build_service(settings)
    with pytest.raises(InvalidRequestError):
        await service.search_in_bounds(BBox(30, -100, 35, -95))


async def test_small_pans_share_cache_entry(settings):
    primary = FakePrimary()
    service = build_service(settings, primary=primary)
    await service.search_in_bounds(BBox(30.2612, -97.7488, 30.2987, -97.7011))
    await service.search_in_bounds(BBox(30.2631, -97.7470, 30.2999, -97.7003))
    assert len(primary.bbox_calls) == 1


async def test_too_many_results_warns(settings):
    settings.max_results = 2
    primary = FakePrimary([make_park(f"osm-way-{i}", f"Park {i}", 30.2 + i / 100, -97.7) for i in range(2)])
    result = await build_service(settings, primary=primary).search_in_bounds(BBox(30, -98, 30.5, -97.5))
    assert any("zoom in" in w for w in result.warnings)


async def test_get_park_from_recent_search(settings):
    primary = FakePrimary([make_park("osm-way-7", "Seven Park")])
    service = build_service(settings, primary=primary)
    await service.search_in_bounds(BBox(30, -98, 30.5, -97.5))
    park = await service.get_park("osm-way-7")
    assert park.name == "Seven Park" and primary.id_calls == []


async def test_get_park_fetches_unknown_osm_id(settings):
    primary = FakePrimary([make_park("osm-way-8", "Eight Park")])
    service = build_service(settings, primary=primary)
    assert (await service.get_park("osm-way-8")).name == "Eight Park"
    assert primary.id_calls == ["osm-way-8"]


async def test_get_park_from_sample(settings):
    assert (await build_service(settings).get_park("prospect-park")).rating == 4.7


async def test_get_park_not_found(settings):
    with pytest.raises(NotFoundError):
        await build_service(settings, primary=FakePrimary([])).get_park("osm-way-404")
    with pytest.raises(NotFoundError):
        await build_service(settings).get_park("unknown-park")


async def test_get_park_upstream_failure_is_503(settings):
    service = build_service(settings, primary=FakePrimary(exc=UpstreamError("down")))
    with pytest.raises(ServiceUnavailableError):
        await service.get_park("osm-way-1")
