from bfg.web.services.block_service import BLOCK_SCHEMAS


def test_block_schema_contains_expected_defaults():
    schema = BLOCK_SCHEMAS["hero_carousel_v1"]
    assert schema["settings"]["autoPlay"]["default"] is True
    assert schema["data"]["slides"]["required"] is True


def test_category_grid_without_cms_categories_is_left_unresolved(db):
    """A shop workspace has no web.Category rows; the grid must fall through.

    The clients treat any resolvedData list as the final answer, so stamping []
    here rendered an empty grid instead of letting them fetch product categories.
    """
    from bfg.common.services.workspace_service import WorkspaceService
    from bfg.web.services.block_service import BlockService

    workspace = WorkspaceService(workspace=None, user=None).create_workspace(
        name="Grid WS", slug="grid-ws",
    )
    block = {"type": "category_grid_v1", "data": {"source": "promo"}}

    resolved = BlockService(workspace=workspace, user=None).resolve_block_data(block)

    assert "resolvedData" not in resolved
