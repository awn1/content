from enum import Enum
from typing import Any
from typing import Optional


class SearchTableOperator(Enum):
    WILDCARD = 'WILDCARD', "="
    EQ = 'EQ', "="
    CONTAINS = 'CONTAINS', "contains"
    RANGE = 'RANGE', "="

    def __init__(self, operator_type: str, operator_type_pretty: str):
        self.operator_type = operator_type
        self.operator_type_pretty = operator_type_pretty

    @property
    def value(self) -> str:
        return self.operator_type


class SearchTableField(Enum):
    ALERT_NAME = 'alert_name', "alert name", SearchTableOperator.WILDCARD
    ALERT_TYPE = 'alert_type', "alert type", SearchTableOperator.EQ
    ALERT_ID = 'internal_id', "alert id", SearchTableOperator.EQ
    CASE_ID = 'CASE_ID', "case id", SearchTableOperator.EQ
    API_KEY_ID = 'API_KEY_ID', "api key id", SearchTableOperator.EQ
    AUDIT_DESCRIPTION = 'AUDIT_DESCRIPTION', "audit description", SearchTableOperator.CONTAINS
    AUDIT_OWNER_EMAIL = 'AUDIT_OWNER_EMAIL', "audit email", SearchTableOperator.CONTAINS
    SOURCE_INSTANCE = 'sourceInstance', "source instance", SearchTableOperator.CONTAINS
    CUSTOM = '', "custom field", SearchTableOperator.CONTAINS
    SOURCE_INSERT_TS = 'source_insert_ts', "source insert timestamp", SearchTableOperator.RANGE
    NAME = 'NAME', "NAME", SearchTableOperator.CONTAINS
    AUDIT_INSERT_TIME = 'AUDIT_INSERT_TIME', "audit insert time", SearchTableOperator.RANGE
    INTEGRATION_LOG_INSTANCE = 'INTEGRATION_LOG_INSTANCE', "integration log instance", SearchTableOperator.CONTAINS
    INTEGRATION_LOG_TIMESTAMP = 'INTEGRATION_LOG_TIMESTAMP', "integration log timestamp", SearchTableOperator.RANGE

    def __init__(self, alert_field: str, alerts_field_pretty: str, search_type: SearchTableOperator):
        self.field = alert_field
        self.field_pretty = alerts_field_pretty
        self.search_type = search_type

    @property
    def value(self) -> str:
        return self.field

    @staticmethod
    def custom_field(field_name: str) -> 'SearchTableField':
        """Search field that will be generated on the fly with the required field name"""
        field = SearchTableField.CUSTOM
        field.field_pretty = field_name
        field.field = field_name
        return field

    def create_search_filter(self, search_value: Any, search_type: Optional[SearchTableOperator] = None) -> dict:
        search_type = search_type or self.search_type
        return {"SEARCH_FIELD": self.value, "SEARCH_TYPE": search_type.value, "SEARCH_VALUE": search_value}

    def create_search_filter_pretty(self, search_value: str, data_type: str = "TEXT") -> list[dict]:
        return [
            {
                "pretty_name": self.field_pretty,
                "data_type": data_type,
                "render_type": "attribute",
                "entity_map": None,
                "dml_type": None,
            },
            {"pretty_name": self.search_type.operator_type_pretty, "data_type": None, "render_type": "operator",
             "entity_map": None},
            {"pretty_name": search_value, "data_type": None, "render_type": "value", "entity_map": None},
        ]
