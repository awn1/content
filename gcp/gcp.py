from functools import lru_cache
from typing import Iterator, Optional
from google.oauth2.service_account import Credentials
from google.cloud import compute_v1
import re


CREDS = None


def creds(creds_file: Optional[str] = None):
    global CREDS
    if CREDS is None and creds_file is not None:
        CREDS = Credentials.from_service_account_file(creds_file)
        Images.images_client = compute_v1.MachineImagesClient(
            credentials=CREDS)
        Instance.instance_client = compute_v1.InstancesClient(
            credentials=CREDS)
    return CREDS


class Images:
    images_client = None

    zone_patern = re.compile(
        r"^https:\/\/www\.googleapis\.com\/compute\/v\d\/projects\/[a-z\-]+\/zones\/(?P<zone>[a-z\-\d]+)\/instances\/[a-z\-\d]+$"
    )

    @staticmethod
    def get_image_zone(image: compute_v1.MachineImage) -> str:
        return re.match(
            Images.zone_patern, image.source_instance).group('zone')

    @lru_cache
    @staticmethod
    def images_for_server_version(version: str) -> Iterator[compute_v1.MachineImage]:
        return Images.images_client.list(
            request=compute_v1.ListMachineImagesRequest(
                project=creds().project_id,
                filter=f'name:server-image-{version}-*',
            )
        )

    @staticmethod
    def get_latest_image(version: str):
        *_, latest = Images.images_for_server_version(version)
        return latest

    @staticmethod
    def delete(version: str, amount: int):
        images_to_delete = list(
            Images.images_for_server_version(version))[amount:]
        for image in images_to_delete:
            Images.images_client.delete(
                machine_image=image.name,
                project=creds().project_id
            )


class Instance:
    instance_client = None

    @staticmethod
    def create(instance_name: str, image: compute_v1.MachineImage):
        Instance.instance_client.insert(
            request=compute_v1.InsertInstanceRequest(
                project=creds().project_id,
                zone=Images.get_image_zone(image),
                source_machine_image=image.self_link,
                instance_resource=compute_v1.types.Instance(
                    name=instance_name
                )
            )
        )

    @staticmethod
    def describe(instance_name: str, instance_zone: str):
        return Instance.instance_client.get(
            instance=instance_name,
            project=creds().project_id,
            zone=instance_zone
        )
