import pytest


@pytest.mark.parametrize(
    "packs_to_update, expected_result",
    [
        # update 1 pack
        ("pack1:1.0.0", {"pack1": "1.0.0"}),
        # update 2 packs
        ("pack1:1.0.0,pack2: 1.0.0", {"pack1": "1.0.0", "pack2": "1.0.0"}),
        # no packs to update
        ("", "The parameter 'PACK_VERSIONS', should be in the format: pack1:1.0.0,pack2:1.0.0"),
    ],
)
def test_parse_packs_to_update(packs_to_update, expected_result, mocker):
    """
    Given:
        1. 1 pack to update and it's version.
        2. 2 packs to update and it's version.
        3. no pack to update, an empty string.
    When:
       - running the override core packs pipeline, in the function parse_packs_to_update, verify that the packs
       are parsed correctly.
    Then:
        1+2. validate that we parse it correctly
        3. validate that we get an error.
    """
    from Tests.Marketplace.create_updated_core_packs_list import parse_packs_to_update

    if packs_to_update:
        result = parse_packs_to_update(packs_to_update)
        assert result == expected_result
    else:
        logging_mock = mocker.patch("Tests.Marketplace.create_updated_core_packs_list.logging.error")
        try:
            parse_packs_to_update(packs_to_update)
        except SystemExit:
            logging_mock.assert_called_with(expected_result)


def test_create_updated_corepacks_list():
    """
    Given:
        The current core packs list, a dict of the packs to update and their version, a server_version and the name of
        the bucket.
    When:
        Creating a new and updated core packs list.
    Then:
        verify the returned list.
    """
    from Tests.Marketplace.create_updated_core_packs_list import create_updated_corepacks_list

    corepacks_current_list = ["pack/1.1.1/pack.zip", "pack1/1.1.1/pack1.zip", "pack2/2.2.2/pack2.zip", "pack3/3.3.3/pack3.zip"]
    packs_to_update = {"pack": "1.1.2"}
    server_version = "8.5"
    marketplace_bucket_name = "marketplace-dist"
    expected_result = {"pack/1.1.2/pack.zip", "pack1/1.1.1/pack1.zip", "pack2/2.2.2/pack2.zip", "pack3/3.3.3/pack3.zip"}
    result = create_updated_corepacks_list(corepacks_current_list, packs_to_update, server_version, marketplace_bucket_name)
    result_set = set(result)
    assert result_set == expected_result


def test_get_buckets_from_marketplaces():
    """
    Given:
        A comma separated list of the relevant marketplaces.
    When:
        Retrieving the name of the marketplaces buckets.
    Then:
        verify the returned list.
    """
    from Tests.Marketplace.common import get_buckets_from_marketplaces

    marketplaces = "xsoar_saas,marketplacev2,xpanse"
    expected_prod_result = ["marketplace-saas-dist", "marketplace-v2-dist", "xpanse-dist"]
    expected_dev_result = ["marketplace-saas-dist-dev", "marketplace-v2-dist-dev", "xpanse-dist-dev"]
    result_prod, result_dev = get_buckets_from_marketplaces(marketplaces)
    assert result_prod == expected_prod_result
    assert result_dev == expected_dev_result

    # 1 marketplace
    marketplace1 = "xsoar_saas"
    expected_xsoarsaas_prod = ["marketplace-saas-dist"]
    expected_xsoarsaas_dev = ["marketplace-saas-dist-dev"]
    result1_prod, result1_dev = get_buckets_from_marketplaces(marketplace1)
    assert result1_prod == expected_xsoarsaas_prod
    assert result1_dev == expected_xsoarsaas_dev


def test_validate_core_packs_params_valid_packs(mocker):
    """
    Given:
        A dictionary of the packs to update with the version, the list of the current core packs, the name of the
        relevant bucket.
    When:
        Validating that the packs from the inputs are in the core packs list.
    Then:
        Verify that we get the expected result.
    """
    from Tests.Marketplace.create_updated_core_packs_list import validate_core_packs_params

    packs_to_update = {"pack1": "1.2.3", "pack2": "2.3.4"}
    upgrade_core_packs = ["pack1", "pack2", "pack3", "pack4"]
    marketplace_bucket = "bucket"
    packs_list = list(packs_to_update.keys())
    logging_mock = mocker.patch("Tests.Marketplace.create_updated_core_packs_list.logging.debug")
    validate_core_packs_params(packs_to_update, upgrade_core_packs, marketplace_bucket)
    logging_mock.assert_called_with(
        f"The packs {packs_list} are on the core packs list {upgrade_core_packs} for the " f"bucket {marketplace_bucket}"
    )


def test_validate_core_packs_params_non_valid_packs(mocker):
    """
    Given:
        A dictionary of the packs to update with the version, the list of the current core packs, the name of the
        relevant bucket.
    When:
        Validating that the packs from the inputs are in the core packs list.
    Then:
        Verify that we get the expected result.
    """
    from Tests.Marketplace.create_updated_core_packs_list import validate_core_packs_params

    packs_to_update = {"pack1": "1.2.3"}
    upgrade_core_packs = ["pack2", "pack3", "pack4"]
    marketplace_bucket = "bucket"
    packs_list = list(packs_to_update.keys())
    logging_mock = mocker.patch("Tests.Marketplace.create_updated_core_packs_list.logging.error")
    try:
        validate_core_packs_params(packs_to_update, upgrade_core_packs, marketplace_bucket)
    except SystemExit:
        logging_mock.assert_called_with(
            f"The packs {packs_list} aren't in the core packs list {upgrade_core_packs} for" f" the bucket {marketplace_bucket}."
        )
