import logging
from contextlib import contextmanager
from typing import Any, Union

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore

from infra.resources.constants import AUTOMATION_GCP_PROJECT
from infra.utils.rocket_retry import retry
from infra.utils.text import ConnectorName
from infra.utils.time_utils import time_now

logger = logging.getLogger(__name__)


class LockedException(Exception):
    """Raised exception for file-lock"""


class Firestore:
    """
    Firestore connector to share key:value documents between tenants/test runs
    """

    connector_name = ConnectorName()

    def __init__(self, project=AUTOMATION_GCP_PROJECT):
        self.client = firestore.Client(project=project)
        # self.inc_metric = partial(metrics_client.incr, self.connector_name)

    def _get_doc(self, collection, document):
        # self.inc_metric('get_doc')
        return self.client.collection(collection).document(document).get()

    def _set_doc(self, collection, document, data: dict):
        # self.inc_metric('set_doc')
        return self.client.collection(collection).document(document).set(data)

    def _update_doc(self, collection, document, data: dict):
        # self.inc_metric('update_doc')
        return self.client.collection(collection).document(document).update(data)

    def get_document_field(self, collection, document, field: str) -> Union[dict, str]:
        """Get document field, returns empty dict if field does not exist"""
        if document_data := self._get_doc(collection=collection, document=document).to_dict():
            return document_data.get(field, {})
        return {}

    def update_document_field(self, collection, document, field_name: str, field_value: Any):
        """Update document field"""
        self._update_doc(collection=collection, document=document, data={firestore.Client.field_path(field_name): field_value})

    @retry(exceptions=LockedException, tries=15, delay=20, raise_original_exception=True)
    def create_lock(self, collection, document, lock_field_name: str):
        """Create lock in firestore by adding a field to token_mgmt_ref document"""
        # self.inc_metric('create_lock')
        all_cookies = self._get_doc(collection=collection, document=document)
        if not all_cookies.exists:
            logger.warning(f'{collection} does not have {document=}, creating document')
            self._set_doc(collection=collection, document=document, data={})
        elif all_cookies.to_dict().get(lock_field_name) and all_cookies.update_time > time_now().subtract(minutes=5):
            raise LockedException(f'The {lock_field_name=} exists and is recent enough')
        logger.debug(f'Creating {lock_field_name=}')
        # TODO: handle case where 2 sessions get to here at exactly the same time
        self.update_document_field(collection=collection, document=document, field_name=lock_field_name, field_value=True)

    def release_lock(self, collection, document, lock_field_name: str):
        """Release the lock by deleting the lock field from token_mgmt_ref document"""
        logger.debug(f'Releasing lock on {lock_field_name=}')
        self.update_document_field(collection=collection, document=document,
                                   field_name=lock_field_name, field_value=firestore.DELETE_FIELD)


@contextmanager
def lock_and_read(fs_client: Firestore, collection, document, field) -> dict:
    """FireStore context manager to read values and lock them for reading of others until the context operation is done"""
    should_release_lock = True  # by default release lock otherwise we can fail using the data and not release the lock
    lock_field_name = f'{field}_lock'
    try:
        fs_client.create_lock(collection=collection, document=document, lock_field_name=lock_field_name)
        fs_data = fs_client.get_document_field(collection=collection, document=document, field=field)
        yield fs_data
    except LockedException as e:
        logger.error(f'FireStore: {e}')
        should_release_lock = False
        raise
    except GoogleAPICallError as e:
        should_release_lock = False
        raise Exception(f'Failed getting {collection=} {document=} data from FireStore, check permissions') from e
    finally:
        # if lock is used by another session, do not release it
        if should_release_lock:
            fs_client.release_lock(collection=collection, document=document, lock_field_name=lock_field_name)
