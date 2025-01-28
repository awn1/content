import pytest


@pytest.mark.parametrize(
    "marketplace, expected_result",
    [
        # update 1 pack
        ("marketplacev2", {"group1": {"packs": [{"id": "pack1", "version": "1.0.0"}, {"id": "pack2", "version": "2.0.0"}]}}),
        # update 2 packs
        (
            "xsoar",
            {
                "group1": {"packs": [{"id": "pack1", "version": "1.0.0"}, {"id": "pack2", "version": "2.0.0"}]},
                "group2": {"packs": [{"id": "pack3", "version": "3.0.0"}, {"id": "pack4", "version": "4.0.0"}]},
            },
        ),
        # no packs to update
        ("xpanse", {}),
    ],
    ids=["1 group to update (marketplacev2)", "2 groups to update (xsoar)", "no group to update (xspanse)"],
)
def test_filter_groups_per_marketplace(marketplace, expected_result):
    """
    Given:
        A parsed file and a marketplace name.
        1. 1 group to update and it's packs.
        2. 2 groups to update and it's packs.
        3. no group to update.
    When:
       Running the function.
    Then:
        Verify we get filtered groups per marketplace.
    """
    from Tests.Marketplace.deploy_groups_file import filter_groups_per_marketplace

    parsed_file = {
        "group1": {
            "packs": [{"id": "pack1", "version": "1.0.0"}, {"id": "pack2", "version": "2.0.0"}],
            "marketplaces": ["xsoar", "marketplacev2"],
        },
        "group2": {
            "packs": [{"id": "pack3", "version": "3.0.0"}, {"id": "pack4", "version": "4.0.0"}],
            "marketplaces": ["xsoar"],
        },
    }
    result = filter_groups_per_marketplace(parsed_file, marketplace)
    assert result == expected_result
