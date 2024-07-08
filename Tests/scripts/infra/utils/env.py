import os

from distutils.util import strtobool

from infra.resources.constants import CI_PIPELINE_SOURCE
from infra.resources.constants import IS_MSSP_TENANT
from infra.resources.constants import IS_PROD_ENV_PATH
# from build_machines.resources.constants import ROCKET_BRANCH


def is_production() -> bool:
    """return is the run executed on production environment"""
    prod = os.getenv(IS_PROD_ENV_PATH) or 'no'
    return bool(strtobool(prod))


def is_mssp_tenant() -> bool:
    """return is the run executed on MSSP tenant"""
    is_mssp = os.getenv(IS_MSSP_TENANT) or 'no'
    return bool(strtobool(is_mssp))


# def is_jenkins() -> bool:
#     """return is the run executed on jenkins or not"""
#     return bool(os.getenv(ROCKET_BRANCH))


def is_gitlab_pipeline() -> bool:
    """return is the run executed on gitlab pipelines or not"""
    return bool(os.getenv(CI_PIPELINE_SOURCE))


def is_unit_test_run(pytest_config):
    """return is the run executes unit tests"""
    return 'unit_test' in pytest_config.invocation_dir.strpath or is_gitlab_pipeline()
