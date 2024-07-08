import datetime
from typing import Optional, Union

from infra.enums.papi import KeySecurityLevel


class PublicApiKey:
    id: str
    key: str
    comment: Optional[str]
    roles: Optional[Union[str, list[str]]]
    security_level: Optional[KeySecurityLevel]
    expiration: Optional[datetime.datetime]
    creation_time: Optional[datetime.datetime]
    created_by: Optional[str]
    user_name: Optional[str]

    def __init__(self, id: str, key: str, comment: Optional[str] = None,
                 roles: Optional[Union[str, list[str]]] = None,
                 security_level: Optional[KeySecurityLevel] = None,
                 expiration: Optional[datetime.datetime] = None,
                 creation_time: Optional[datetime.datetime] = None,
                 created_by: Optional[str] = None,
                 user_name: Optional[str] = None):
        self.id = id
        self.key = key
        self.comment = comment
        self.roles = roles
        self.security_level = security_level
        self.expiration = expiration
        self.creation_time = creation_time
        self.created_by = created_by
        self.user_name = user_name