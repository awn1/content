from functools import lru_cache
from typing import Iterator
from google.oauth2.service_account import Credentials
from google.cloud import compute_v1
import re


class Images:

    def __init__(self, creds: str | Credentials):
        credentials = creds if isinstance(
            creds, Credentials) else Credentials.from_service_account_file(creds)
        self.project_id = credentials.project_id
        self.images_client = compute_v1.MachineImagesClient(
            credentials=credentials)

    zone_patern = re.compile(
        r"^https:\/\/www\.googleapis\.com\/compute\/v\d\/projects\/[a-z\-]+\/zones\/(?P<zone>[a-z\-\d]+)\/instances\/[a-z\-\d]+$"
    )

    @staticmethod
    def get_image_zone(image: compute_v1.MachineImage) -> str:
        return re.match(
            Images.zone_patern, image.source_instance).group('zone')

    def images_for_server_version(self, version: str) -> Iterator[compute_v1.MachineImage]:
        return self.images_client.list(
            request=compute_v1.ListMachineImagesRequest(
                project=self.project_id,
                filter=f'name:server-image-{version}-*',
            )
        )

    @lru_cache
    def get_latest_image(self, version: str):
        *_, latest = self.images_for_server_version(version)
        return latest

    def delete(self, version: str, amount: int):
        images_to_delete = list(
            self.images_for_server_version(version))[amount:]
        for image in images_to_delete:
            self.images_client.delete(
                machine_image=image.name,
                project=self.project_id
            )


class Instance:

    def __init__(self, creds: str | Credentials):
        credentials = creds if isinstance(
            creds, Credentials) else Credentials.from_service_account_file(creds)
        self.project_id = credentials.project_id
        self.instance_client = compute_v1.InstancesClient(
            credentials=credentials)
        self.image_client = Images(credentials)

    def create(self, instance_name: str, image: compute_v1.MachineImage) -> str:
        insert_op = self.instance_client.insert(
            request=compute_v1.InsertInstanceRequest(
                project=self.project_id,
                zone=self.image_client.get_image_zone(image),
                source_machine_image=image.self_link,
                instance_resource=compute_v1.types.Instance(
                    name=instance_name
                )
            )
        )
        insert_op.done()
        return self.instance_client.get(
            instance=instance_name,
            project=self.project_id,
            zone=self.image_client.get_image_zone(image)
        ).network_interfaces[0].network_i_p

    def describe(self, instance_name: str, instance_zone: str):
        return self.instance_client.get(
            instance=instance_name,
            project=self.project_id,
            zone=instance_zone
        )
