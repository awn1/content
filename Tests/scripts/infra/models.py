import datetime

from Tests.scripts.infra.enums.papi import KeySecurityLevel


class PublicApiKey:
    id: str
    key: str
    comment: str | None
    roles: str | list[str] | None
    security_level: KeySecurityLevel | None
    expiration: datetime.datetime | None
    creation_time: datetime.datetime | None
    created_by: str | None
    user_name: str | None

    def __init__(
        self,
        id: str,
        key: str,
        comment: str | None = None,
        roles: str | list[str] | None = None,
        security_level: KeySecurityLevel | None = None,
        expiration: datetime.datetime | None = None,
        creation_time: datetime.datetime | None = None,
        created_by: str | None = None,
        user_name: str | None = None,
    ):
        self.id = id
        self.key = key
        self.comment = comment
        self.roles = roles
        self.security_level = security_level
        self.expiration = expiration
        self.creation_time = creation_time
        self.created_by = created_by
        self.user_name = user_name

    @staticmethod
    def parse_api_key_from_table_data(key):
        return PublicApiKey(
            id=key.get("API_KEY_ID"),
            key=key.get("API_KEY"),
            comment=key.get("API_KEY_COMMENT"),
            roles=key.get("API_KEY_RBAC_ROLES"),
            security_level=key.get("API_KEY_SECURITY_LEVEL"),
            expiration=PublicApiKey.parse_expiration(key.get("API_KEY_EXPIRATION_TIME")),
            creation_time=key.get("API_KEY_CREATION_TIME"),
            created_by=key.get("API_KEY_CREATED_BY"),
            user_name=key.get("API_KEY_PRETTY_USER"),
        )

    @staticmethod
    def parse_expiration(api_key_expiration_time):
        return datetime.datetime.fromtimestamp(float(api_key_expiration_time) / 1000) if api_key_expiration_time else None
