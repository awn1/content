from loguru import logger

logger.level("INFO")


ENGINE_PREFIX = "engine-"


def add_engine_prefix(project_id: str):
    if not project_id.startswith(ENGINE_PREFIX):
        return f"{ENGINE_PREFIX}{project_id}"
    return project_id


def remove_engine_prefix(project_id: str):
    return project_id.removeprefix(ENGINE_PREFIX)
