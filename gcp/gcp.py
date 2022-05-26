from typing import Iterator, Optional
from google.oauth2.service_account import Credentials
from google.cloud import compute_v1


CREDS = None


def creds(creds_file: Optional[str] = None):
    global CREDS
    if CREDS is None and creds_file is None:
        CREDS = Credentials.from_service_account_file(creds_file)
    return CREDS


class Images:
    images_client = compute_v1.MachineImagesClient(creds())

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
    def delete_images(version: str, from_date: str):
        for image in Images.images_for_server_version(version):
            if Images.creation_timestamp < from_date:
                Images.images_client.delete(image)


class Instance:
    instance_client = compute_v1.InstancesClient(creds())

    @staticmethod
    def create(instance_name: str, iamge: compute_v1.MachineImage):
        Instance.instance_client.insert(
            request=compute_v1.InsertInstanceRequest(
                project=creds().project_id,
                zone=iamge.zone,
                source_machine_image=iamge.self_link,
                instance_resource=compute_v1.types.Instance(
                    name=instance_name
                )
            )
        )
