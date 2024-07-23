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

    def __init__(self, id: str, key: str, comment: str | None = None,
                 roles: str | list[str] | None = None,
                 security_level: KeySecurityLevel | None = None,
                 expiration: datetime.datetime | None = None,
                 creation_time: datetime.datetime | None = None,
                 created_by: str | None = None,
                 user_name: str | None = None):
        self.id = id
        self.key = key
        self.comment = comment
        self.roles = roles
        self.security_level = security_level
        self.expiration = expiration
        self.creation_time = creation_time
        self.created_by = created_by
        self.user_name = user_name