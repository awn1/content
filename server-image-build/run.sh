#!/bin/sh
time docker run -t --rm \
    --env CI=$CI --env XSOAR_ADMIN_PASS=$XSOAR_ADMIN_PASS --env BASE_INSTANCE_NAME=$BASE_INSTANCE_NAME \
    --env INSTALLER_URL=$INSTALLER_URL --env SERVER_IMG_NAME=$SERVER_IMG_NAME --env VERSION=$VERSION \
    --env CI_PIPELINE_ID=$CI_PIPELINE_ID \
    --mount type=bind,source=$(pwd)/server-image-build,target=/server-image-build \
    --mount "type=bind,source=$XSOAR_CONTENT_BUILD_CREDS,target=/server-image-build/secrets/xsoar_content_build_creds" \
    --mount "type=bind,source=$XSOAR_SERVER_STORAGE_CREDS,target=/server-image-build/secrets/xsoar_server_storage_creds" \
    --mount "type=bind,source=$OREGON_CI_KEY,target=/server-image-build/secrets/ssh_key" \
    test/server-image-build
