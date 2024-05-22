from infra.secret_manager import SecretManager


class Secret:
    secrets_client = SecretManager()

    def __init__(self, name):
        self.name = name

    def __get__(self, instance, class_) -> str:
        return self.secrets_client.get_secret(secret_id=self.name)


class JiraConfig:
    server = "https://jira-dc.paloaltonetworks.com"
    server_hq = "https://jira-hq.paloaltonetworks.local"
    username = Secret('jira_username')
    password = Secret('jira_password')
    pat_token = Secret('jira_pat_token')


class RocketUser:
    username: str
    password: str


class XSOARAdminUser(RocketUser):
    username = Secret('xsoar_administrator_username')
    password = Secret('xsoar_administrator_password')


class XSOARRestrictedUser(RocketUser):
    username = Secret('xsoar_restricted_username')
    password = Secret('xsoar_restricted_password')


class XSOARViewerUser(RocketUser):
    username = Secret('xsoar_viewer_username')
    password = Secret('xsoar_viewer_password')


class XSOARExtendedEditorUser(RocketUser):
    username = Secret('xsoar_extended_editor_username')
    password = Secret('xsoar_extended_editor_password')


class XSOAROnTheFlyUser(RocketUser):
    username = Secret('xsoar_on_the_fly_username')
    password = Secret('xsoar_on_the_fly_password')


class XSOAREditorUser(RocketUser):
    username = Secret('xsoar_editor_username')
    password = Secret('xsoar_editor_password')


class XSOARPremAdminUser(RocketUser):
    username = Secret('xsoar_prem_administrator_username')
    password = Secret('xsoar_prem_administrator_password')


class XSOAROppAdminUser(RocketUser):
    username = Secret('xsoar_opp_administrator_username')
    password = Secret('xsoar_opp_administrator_password')


class XSOAROppRestrictedUser(RocketUser):
    username = Secret('xsoar_opp_restricted_username')
    password = Secret('xsoar_opp_restricted_password')


class XSOAROppViewerUser(RocketUser):
    username = Secret('xsoar_opp_viewer_username')
    password = Secret('xsoar_opp_viewer_password')


class XSOAROppEditorUser(RocketUser):
    username = Secret('xsoar_opp_editor_username')
    password = Secret('xsoar_opp_editor_password')


class XSOAROppExtendedEditorUser(RocketUser):
    username = Secret('xsoar_opp_extended_editor_username')
    password = Secret('xsoar_opp_extended_editor_password')


class XSOAROppOnTheFlyUser(RocketUser):
    username = Secret('xsoar_opp_on_the_fly_username')
    password = Secret('xsoar_opp_on_the_fly_password')


class SelfServiceUser:
    host = 'xsoar-selfservice.gcp.pan.local'
    username = Secret('xsoar_self_service_username')
    password = Secret('xsoar_self_service_password')


class OPPConnection:
    username = Secret('opp_ssh_username')
    password = Secret('opp_ssh_password')


class GmailTestUser:
    """Test user credentials"""

    credentials = Secret('google_api_test_user_credentials')
    token = Secret('google_api_test_user_token')


class GmailProdTestUser:
    """Test user credentials marked as prod (same user as test user)"""

    credentials = Secret('google_api_prod_test_user_credentials')
    token = Secret('google_api_prod_test_user_token')


class Service:
    google_api_credentials = Secret('google_api_credentials')
    google_api_token = Secret('google_api_token')
    gmail_test_user = GmailTestUser()
    gmail_prod_user = GmailProdTestUser()
    google_api_rocket_sender_user_credentials = Secret('google_api_rocket_sender_user_credentials')
    google_api_rocket_sender_user_token = Secret('google_api_rocket_sender_user_token')
    autofocus_integration_api_key = Secret('autofocus_integration_api_key')


class Settings:
    jira = JiraConfig()
    xsoar_admin_user = XSOARAdminUser()
    xsoar_restricted_user = XSOARRestrictedUser()
    xsoar_view_user = XSOARViewerUser()
    xsoar_editor_user = XSOAREditorUser()
    xsoar_extended_editor_user = XSOARExtendedEditorUser()
    xsoar_on_the_fly_user = XSOAROnTheFlyUser()
    xsoar_prem_admin_user = XSOARPremAdminUser()
    xsoar_opp_admin_user = XSOAROppAdminUser()
    xsoar_opp_restricted_user = XSOAROppRestrictedUser()
    xsoar_opp_view_user = XSOAROppViewerUser()
    xsoar_opp_editor_user = XSOAROppEditorUser()
    xsoar_opp_extended_editor_user = XSOAROppExtendedEditorUser()
    xsoar_opp_on_the_fly_user = XSOAROppOnTheFlyUser()
    service = Service()
    opp_connection = OPPConnection()
