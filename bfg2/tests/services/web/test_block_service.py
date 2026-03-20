from bfg.web.services.block_service import BLOCK_SCHEMAS


def test_block_schema_contains_expected_defaults():
    schema = BLOCK_SCHEMAS["hero_carousel_v1"]
    assert schema["settings"]["autoPlay"]["default"] is True
    assert schema["data"]["slides"]["required"] is True
