import httpx
import pytest
import respx

from app.errors import CityNotFoundError, UpstreamError, UpstreamRateLimitedError
from app.geo import BBox
from app.providers.nominatim import NominatimGeocoder, parse_result
from app.providers.overpass import OverpassParkProvider, build_bbox_query, parse_element, parse_elements
from app.providers.sample import SampleParkProvider
from app.rate_limit import MinIntervalLimiter

BOX = BBox(30.1, -97.9, 30.5, -97.6)


# --------------------------------------------------------------------------- Overpass parsing

class TestParseElement:
    def test_node(self):
        park = parse_element({"type": "node", "id": 1, "lat": 30.2, "lon": -97.7, "tags": {"name": "Pease Park"}})
        assert park is not None
        assert park.id == "osm-node-1" and park.name == "Pease Park"
        assert park.source == "openstreetmap"

    def test_polygon_uses_center(self):
        park = parse_element({"type": "way", "id": 2, "center": {"lat": 30.26, "lon": -97.77},
                              "tags": {"name": "Zilker Park"}})
        assert park is not None and park.location.lat == 30.26 and park.location.lng == -97.77

    def test_relation_multipolygon(self):
        park = parse_element({"type": "relation", "id": 3, "center": {"lat": 30.3, "lon": -97.7},
                              "tags": {"name": "Big Park", "type": "multipolygon"}})
        assert park is not None and park.id == "osm-relation-3"

    def test_maps_optional_tags_without_inventing(self):
        park = parse_element({
            "type": "way", "id": 4, "center": {"lat": 30.3, "lon": -97.7},
            "tags": {
                "name": "Full Park", "description": "Lovely", "opening_hours": "Mo-Su 05:00-22:00",
                "addr:housenumber": "2100", "addr:street": "Barton Springs Rd", "addr:city": "Austin",
                "addr:state": "TX", "addr:postcode": "78704", "toilets": "yes", "dog": "leashed",
                "wheelchair": "no", "website": "https://austintexas.gov", "image": "https://img.test/a.jpg",
            },
        })
        assert park is not None
        assert park.description == "Lovely"
        assert park.hours == "Mo-Su 05:00-22:00"
        assert park.location.address == "2100 Barton Springs Rd, Austin, TX 78704"
        assert park.amenities == ["restrooms", "dogs-allowed"]  # wheelchair=no is not an amenity
        assert park.website == "https://austintexas.gov"
        assert park.images == ["https://img.test/a.jpg"]

    def test_missing_optional_fields_are_none(self):
        park = parse_element({"type": "node", "id": 5, "lat": 30.2, "lon": -97.7, "tags": {"name": "Bare"}})
        assert park is not None
        assert park.description is None and park.hours is None and park.location.address is None
        assert park.amenities == [] and park.images == [] and park.acreage is None and park.rating is None

    def test_unsafe_urls_are_dropped(self):
        park = parse_element({"type": "node", "id": 6, "lat": 30.2, "lon": -97.7,
                              "tags": {"name": "P", "image": "javascript:alert(1)", "website": "ftp://x"}})
        assert park is not None and park.images == [] and park.website is None

    @pytest.mark.parametrize("element", [
        None,
        "string",
        {"type": "node", "id": 1, "lat": 30, "lon": -97},  # no tags
        {"type": "node", "id": 1, "lat": 30, "lon": -97, "tags": {}},  # unnamed
        {"type": "node", "id": 1, "lat": 30, "lon": -97, "tags": {"name": "P", "access": "private"}},
        {"type": "way", "id": 1, "tags": {"name": "P"}},  # polygon without center
        {"type": "node", "id": 1, "lat": "x", "lon": -97, "tags": {"name": "P"}},
        {"type": "node", "id": 1, "lat": 0, "lon": 0, "tags": {"name": "P"}},
        {"type": "area", "id": 1, "lat": 30, "lon": -97, "tags": {"name": "P"}},
        {"type": "node", "id": "1", "lat": 30, "lon": -97, "tags": {"name": "P"}},
    ])
    def test_unusable_elements_are_skipped(self, element):
        assert parse_element(element) is None


def test_parse_elements_dedupes_node_and_polygon():
    payload = {"elements": [
        {"type": "node", "id": 1, "lat": 30.2669, "lon": -97.7729, "tags": {"name": "Zilker Park"}},
        {"type": "way", "id": 2, "center": {"lat": 30.2670, "lon": -97.7728},
         "tags": {"name": "Zilker Park", "opening_hours": "05:00-22:00"}},
        {"type": "way", "id": 3, "tags": {"name": "Broken"}},
    ]}
    parks = parse_elements(payload)
    assert [p.id for p in parks] == ["osm-way-2"]


@pytest.mark.parametrize("payload", [None, [], {"elements": "nope"}, {"remark": "runtime error"}])
def test_parse_elements_rejects_bad_payload(payload):
    with pytest.raises(UpstreamError):
        parse_elements(payload)


def test_build_bbox_query_includes_all_geometry_types():
    query = build_bbox_query(BOX, timeout_seconds=20, limit=100)
    assert "[timeout:20]" in query
    for kind in ("node", "way", "relation"):
        assert f'{kind}["leisure"="park"](30.100000,-97.900000,30.500000,-97.600000)' in query
    assert "out tags center 100;" in query


# --------------------------------------------------------------------------- Overpass HTTP

@respx.mock
async def test_overpass_provider_fetches_parks(settings):
    route = respx.post(settings.overpass_url).mock(return_value=httpx.Response(200, json={"elements": [
        {"type": "node", "id": 9, "lat": 30.2, "lon": -97.7, "tags": {"name": "Pease Park"}},
    ]}))
    async with httpx.AsyncClient() as client:
        parks = await OverpassParkProvider(client, settings).parks_in_bbox(BOX)
    assert [p.name for p in parks] == ["Pease Park"]
    assert b"leisure" in route.calls.last.request.content


@respx.mock
async def test_overpass_provider_429_raises_rate_limited(settings):
    respx.post(settings.overpass_url).mock(return_value=httpx.Response(429, headers={"Retry-After": "10"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamRateLimitedError) as info:
            await OverpassParkProvider(client, settings).parks_in_bbox(BOX)
    assert info.value.retry_after == 10


@respx.mock
async def test_overpass_park_by_id(settings):
    respx.post(settings.overpass_url).mock(return_value=httpx.Response(200, json={"elements": [
        {"type": "way", "id": 42, "center": {"lat": 30.2, "lon": -97.7}, "tags": {"name": "Answer Park"}},
    ]}))
    async with httpx.AsyncClient() as client:
        provider = OverpassParkProvider(client, settings)
        park = await provider.park_by_id("osm-way-42")
        assert park is not None and park.name == "Answer Park"
        assert await provider.park_by_id("not-an-osm-id") is None


# --------------------------------------------------------------------------- Nominatim

NOMINATIM_AUSTIN = {
    "lat": "30.2711286", "lon": "-97.7436995", "addresstype": "city",
    "display_name": "Austin, Travis County, Texas, United States",
    "boundingbox": ["30.0985133", "30.5166255", "-97.9367663", "-97.5605288"],
}


def test_parse_result_valid():
    parsed = parse_result(NOMINATIM_AUSTIN)
    assert parsed is not None
    city, kind = parsed
    assert kind == "city" and city.bbox.south == pytest.approx(30.0985133)


@pytest.mark.parametrize("item", [
    None, {}, {"lat": "x", "lon": "1", "boundingbox": ["1", "2", "3", "4"]},
    {**NOMINATIM_AUSTIN, "boundingbox": ["31", "30", "-97", "-98"]},  # inverted
    {**NOMINATIM_AUSTIN, "boundingbox": ["1", "2"]},
])
def test_parse_result_malformed(item):
    assert parse_result(item) is None


@respx.mock
async def test_geocoder_prefers_city_over_other_matches(settings):
    street = {**NOMINATIM_AUSTIN, "addresstype": "road", "display_name": "Austin Street"}
    respx.get(settings.nominatim_url).mock(return_value=httpx.Response(200, json=[street, NOMINATIM_AUSTIN]))
    async with httpx.AsyncClient() as client:
        city = await NominatimGeocoder(client, settings, MinIntervalLimiter(0)).geocode_city("Austin, TX")
    assert city.label.startswith("Austin, Travis County")
    request = respx.calls.last.request
    assert request.url.params["countrycodes"] == "us"


@respx.mock
async def test_geocoder_not_found(settings):
    respx.get(settings.nominatim_url).mock(return_value=httpx.Response(200, json=[]))
    async with httpx.AsyncClient() as client:
        with pytest.raises(CityNotFoundError):
            await NominatimGeocoder(client, settings, MinIntervalLimiter(0)).geocode_city("Atlantis")


@respx.mock
async def test_geocoder_unexpected_payload(settings):
    respx.get(settings.nominatim_url).mock(return_value=httpx.Response(200, json={"error": "x"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(UpstreamError):
            await NominatimGeocoder(client, settings, MinIntervalLimiter(0)).geocode_city("Austin")


# --------------------------------------------------------------------------- Sample data

async def test_sample_provider_skips_malformed_records(sample_path):
    provider = SampleParkProvider(sample_path)
    all_parks = await provider.parks_in_bbox(BBox(-89, -179, 89, 179))
    assert sorted(p.id for p in all_parks) == ["prospect-park", "zilker-park"]
    assert all(p.source == "sample" for p in all_parks)


async def test_sample_provider_city_match(sample_path):
    provider = SampleParkProvider(sample_path)
    assert [p.id for p in await provider.parks_matching_city("Austin, TX")] == ["zilker-park"]
    assert [p.id for p in await provider.parks_matching_city("brooklyn")] == ["prospect-park"]
    assert await provider.parks_matching_city("Aus") == []  # whole words only
    assert await provider.parks_matching_city(" , ") == []


async def test_sample_provider_by_id(sample_path):
    provider = SampleParkProvider(sample_path)
    assert (await provider.park_by_id("zilker-park")).name == "Zilker Park"
    assert await provider.park_by_id("missing") is None


@pytest.mark.parametrize("content", [None, "{not json", '{"a": 1}'])
async def test_sample_provider_tolerates_missing_or_bad_file(tmp_path, content):
    path = tmp_path / "parks.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert await SampleParkProvider(path).parks_in_bbox(BBox(-89, -179, 89, 179)) == []


def test_repo_sample_file_is_valid():
    from app.config import REPO_ROOT
    import json
    from app.models import Park

    data = json.loads((REPO_ROOT / "assets" / "parks.sample.json").read_text(encoding="utf-8"))
    assert data and all(Park.model_validate(item) for item in data)
