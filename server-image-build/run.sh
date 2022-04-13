#!/bin/sh
time docker run -it --rm \
    --env XSOAR_ADMIN_PASS=$XSOAR_ADMIN_PASS --env BASE_INSTANCE_NAME=$BASE_INSTANCE_NAME --env GCS_URL=$GCS_URL --env SERVER_IMG_NAME=$SERVER_IMG_NAME \
    --mount type=bind,source=$(pwd)/server-image-build,target=/server-image-build \
    --mount "type=bind,source=$XSOAR_CONTENT_BUILD_CREDS,target=/server-image-build/secrets/xsoar_content_build_creds" \
    --mount "type=bind,source=$XSOAR_SERVER_STORAGE_CREDS,target=/server-image-build/secrets/xsoar_server_storage_creds" \
    --mount "type=bind,source=$HOME/.ssh/google_compute_engine,target=/server-image-build/secrets/ssh_key" \
    test/server-image-build
