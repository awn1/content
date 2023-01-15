from typing import Dict, Iterator, List, Optional, Tuple
from google.oauth2.service_account import Credentials
from google.cloud import compute_v1
from google.api_core.extended_operation import ExtendedOperation

TEMPLATE_LINK = 'projects/{project_id}/global/instanceTemplates/{template}'
IMAGE_LINK = 'projects/{project_id}/global/images/{image_name}'


class Images:
    def __init__(self, creds: str | Credentials, zone: str):
        credentials = creds if isinstance(
            creds, Credentials) else Credentials.from_service_account_file(creds)
        self.project_id = credentials.project_id
        self.images_client = compute_v1.ImagesClient(credentials=credentials)

    def images_for_server_version(self, version: str) -> Iterator[compute_v1.MachineImage]:
        return self.images_client.list(
            request=compute_v1.ListImagesRequest(
                project=self.project_id,
                filter=f'name:server-image-{version}-*',
            )
        )

    # def delete(self,  version: str, )


class Instance:

    def __init__(self, instance_name: str, project_id: str, zone: str, instance_client: compute_v1.InstancesClient, *,
                 config_dict: Optional[Dict] = {}, source_instance_template: Optional[str] = None,
                 instance_sa: Optional[str] = None, source_image: Optional[str] = None,
                 role: Optional[str] = None):
        self.instance_client = instance_client
        self.instance_name = instance_name
        self.source_instance_template = TEMPLATE_LINK.format(
            project_id=project_id,
            template=source_instance_template or config_dict['template']
        )
        self.instance_sa = (instance_sa or config_dict['serviceaccount']).format(
            project=project_id)
        self.source_image = IMAGE_LINK.format(
            project_id=project_id,
            image_name=source_image or config_dict['imagename']
        )
        self._ip = None
        self.project_id = project_id
        self.role = role or config_dict['role']
        self.zone = zone or config_dict['zone']

    @property
    def ip(self):
        if not self._ip:
            self._ip = self.get_ip_for_instance()
        return self._ip

    def to_dict(self):
        return {
            'InstanceName': self.instance_name,
            'Key': 'oregon-ci',
            'Role': self.role,
            'SSHuser': 'gcp-user',
            'ImageName': self.source_image,
            'TunnelPort': 443,
            'InstanceDNS': self.ip,
            'AvailabilityZone': self.zone
        }

    def get_ip_for_instance(self):
        return self.instance_client.get(instance=self.instance_name, project=self.project_id, zone=self.zone).network_interfaces[0].network_i_p

    def describe(self):
        return self.instance_client.get(
            instance=self.instance_name,
            project=self.project_id,
            zone=self.zone
        )

    def instance_request(self) -> compute_v1.InsertInstanceRequest:
        return compute_v1.Instance(
            name=self.instance_name,
            service_accounts=[
                compute_v1.ServiceAccount(
                    email=self.instance_sa
                )
            ],
            disks=[compute_v1.AttachedDisk(
                auto_delete=True,
                boot=True,
                initialize_params=compute_v1.AttachedDiskInitializeParams(
                    source_image=self.source_image

                )
            )]
        )


class InstanceService:

    def __init__(self, creds: str | Credentials, zone: str):
        credentials = creds if isinstance(
            creds, Credentials) else Credentials.from_service_account_file(creds)

        self.zone = zone
        self.project_id = credentials.project_id
        self.instance_client = compute_v1.InstancesClient(
            credentials=credentials)

    def create_instances(self, instances: List[Dict]):
        insert_extended_operations: ExtendedOperation = []
        redeay_instances = []
        for instance_conf in instances:
            instance_obj = Instance(
                instance_name=instance_conf['name'],
                project_id=self.project_id,
                zone=self.zone,
                instance_client=self.instance_client,
                config_dict=instance_conf
            )
            insert_extended_operations.append((
                self.instance_client.insert(
                    request=compute_v1.InsertInstanceRequest(
                        project=self.project_id,
                        zone=self.zone,
                        source_instance_template=instance_obj.source_instance_template,
                        instance_resource=instance_obj.instance_request())
                )))
            redeay_instances.append(instance_obj)

        while insert_extended_operations:
            insert_extended_operations.pop().result()

        return [instance.to_dict() for instance in redeay_instances]
