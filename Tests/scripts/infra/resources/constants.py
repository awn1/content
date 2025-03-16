import os
from pathlib import Path

AUTOMATION_GCP_PROJECT = "oproxy-dev"

GSM_SERVICE_ACCOUNT = Path(os.environ["GSM_SERVICE_ACCOUNT"]) if "GSM_SERVICE_ACCOUNT" in os.environ else None

# Max allowed validity for public api keys in days
MAX_API_KEY_EXPIRATION_TIME_IN_DAYS = 180
IS_PROD_ENV_PATH = "is_production_tenant"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
)
OKTA_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
OKTA_AUTH_URL = "https://ssopreview.paloaltonetworks.com/api/v1/authn"
OKTA_PROD_AUTH_URL = "https://sso.paloaltonetworks.com/api/v1/authn"
CI_PIPELINE_SOURCE = "CI_PIPELINE_SOURCE"
IS_MSSP_TENANT = "is_mssp_tenant"

COMMENT_FIELD_NAME = "__comment__"

DEFAULT_REQUEST_TIMEOUT = 240


class TokenCache:
    TOKEN_MGMT = "token_mgmt"
    DOCUMENT = "xsoar"
    PROD_DOCUMENT = "xsoar_prod"
    MAX_TTL_HOURS = 7  # Designate this as max ttl for auth cookies to be used
    MIN_TTL_ALLOWED = 4  # Don't use auth cookies which have less than this time left


# XSOAR Role names
class RoleName:
    ROCKET_VIEWER = "rocket view role"
    ROCKET_RESTRICTED = "rocket restricted role"
    ROCKET_EDITOR = "rocket editor role"
    ROCKET_EXTENDED_EDITOR = "rocket extended editor with all flags role"
    ONPREM_VIEWER = "Read-Only"
    XSIAM_VIEWER = "Viewer"
    ONPREM_ANALYST = "Analyst"
    XSIAM_ANALYST = "Investigator"
    NO_ROLE = "No-Role"
    ACCOUNT_ADMIN = "Account Admin"
    INSTANCE_ADMIN = "Instance Administrator"
