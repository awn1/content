# Dockerfiles CICD

This repository comprises our internal automations for the [Dockerfiles](https://github.com/demisto/dockerfiles) repository. **This repository and all of its contents should be considered confidential**.
To work on this pipeline and see your changes reflected in github, add `branch: my_dockerfiles-cicd-dev_branch` under `trigger:` in the github **gitlab-ci.yml** file.
## What is the point of this repository?

Since this repository involves critical information regarding our docker images, both regarding cves we consider to be mitigated, and how the scanning is performed, its important that non PANW employees cannot have access to this pipeline's results or definition.
This works as follows. We have a repository in gitlab [Dockerfiles-Mirror](https://gitlab.xdr.pan.local/xdr/cortex-content/Dockerfiles-Mirror) that mirrors our [github repo](https://github.com/demisto/dockerfiles). The **.gitlab** folder in our github repo is mirrored to gitlab, so it triggers a build on every commit. The pipeline defined there calls this repo's pipeline as a downstream pipeline. The status is reported to the github commit automatically by gitlab.

## On push image scanning

1. We poll for our Circleci workflow to complete, and check which images were created.

2.  2 checks are performed for the docker images built by our Circleci pipeline:
    i. The images are scanned for vulnerabilities using Prisma Cloud (Twistlock).
        1. We send those images to the twistlock console to be scanned.
        2. We parse the resultant report.
    ii. The images are tested using [Connection Test Suite](https://gitlab.xdr.pan.local/xdr/cortex-content/Dockerfiles-CICD/-/blob/main/scripts/SSLTestSuite/README.md).
        1. We create a server using custom nginx configurations.
        2. We then run the client script on the built image and check if the request was recieved successfully.


## How can I mark a cve as mitigated?
If a CVE found by twistlock should be considered as acceptable to us, whether we consider it a false positive, or not applicable for whatever reason, it should be entered into the [**mitigated-cves.json**](./mitigated-cves.json) file as an entry under the image, with the CVE id as the key and the reason as the value.
If a CVE should be considered mitigated for all of our images, enter it under the `*` entry.

## How can I trigger a run for a contribution?

Gitlab pipelines dont run for forked repositories automatically, so we need to trigger it manually. To do this you can run `python trigger_external_run.py --pr {pr_number} --token {TriggerToken}` for example `python trigger_external_run.py --pr 17932 --token 12345`. This will automatically post the status back to the external pr.

You can find the trigger token in [vault](https://console.cloud.google.com/security/secret-manager/secret/Dockerfiles-CICD_trigger_token/versions?organizationId=992524860932&project=xsiam-content-secrets-dev-01).


## CVE content status reports

This reports the cve status of images used in content.

 1. The content graph is used to find the dockerimages used.
 2. The registry scan results are downloaded from twistlock.
 3. Irrelevant results from the registry scan result (not on an image in use/ not high enough severity etc.) are discarded.
 4. The results are grouped by image.

In order for the registry scanner to be scanning the proper repositories, **Launch Twistlock Scan** is run on a schedule about a day before **Generate CVE Report**, to give time for the scan to finish.

## SSL Test Suite
Documentation can be found [here](https://gitlab.xdr.pan.local/xdr/cortex-content/dockerfiles-cicd/-/blob/main/scripts/SSLTestSuite/README.md?ref_type=heads)

