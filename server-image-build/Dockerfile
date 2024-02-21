ARG DOCKER_IO=docker.io
FROM ${DOCKER_IO}/demisto/python3:3.10.4.27798


# Network setup
COPY ci_resources/crt_files/ /usr/local/share/ca-certificates
RUN sed -i -e 's|https://dl-cdn\.alpinelinux\.org|https://art.code.pan.run/artifactory/alpine|g' /etc/apk/repositories
RUN apk add --no-cache --update ca-certificates-cacert
RUN /usr/sbin/update-ca-certificates
RUN apk update
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
COPY ci_resources/pip.conf pip.conf

# Install OpenSSH
RUN mkdir .ssh && apk --update add --no-cache openssh

# Upgrade all packages to latest
# Install ansible and gcloud
# Remove dev dependencies
RUN apk --update add --no-cache --virtual .build-dependencies python3-dev libffi-dev build-base wget \
    && pip install --index-url https://art.code.pan.run/artifactory/api/pypi/pypi.org/simple --trusted-host art.code.pan.run --no-cache-dir ansible google-auth numpy \
    && apk del .build-dependencies

# Install gcloud
RUN wget https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-380.0.0-linux-x86_64.tar.gz -O google-cloud-sdk-380.0.0-linux-x86_64.tar.gz \
    && tar -xf google-cloud-sdk-380.0.0-linux-x86_64.tar.gz \
    && rm google-cloud-sdk-380.0.0-linux-x86_64.tar.gz \
    && /google-cloud-sdk/install.sh --quiet --override-components gsutil core beta
ENV PATH="/google-cloud-sdk/bin:$PATH"
ENV CLOUDSDK_PYTHON_SITEPACKAGES=1

# Configuration
WORKDIR /server-image-build
# ENTRYPOINT [ "/bin/sh" ]
ENTRYPOINT [ "/bin/sh", "-c", "ansible-playbook src/instance-creation.yml" ]

