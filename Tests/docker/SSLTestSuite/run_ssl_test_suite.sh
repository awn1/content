#!/usr/bin/env bash
set -e
RED='\033[0;31m'
NC='\033[0m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'

pushed_images="$1"
if [ -z "${pushed_images}" ]; then
  echo -e "${RED}Please provide the file path as an argument. Exiting.${NC}"
  exit 1
fi

if [ ! -s "${pushed_images}" ]; then
  echo -e "${YELLOW}Pushed images file is empty, exiting without running the tests.${NC}"
  exit 0
fi

images_on_dockerhub=$(sed 's/,$//' "${pushed_images}")
CLIENT_FILES_DIR="client_files"
SERVER_FILES_DIR="server_files"
NGINX_CONFS_PATH="$SERVER_FILES_DIR/nginx_confs"
EXIT_CODE=0

if [ -z "$images_on_dockerhub" ]; then
  echo -e "${YELLOW}No images pushed to the dockerhub. $images_on_dockerhub ${NC}"
  exit 0
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

cd "${SCRIPT_DIR}"

mkdir $SERVER_FILES_DIR/certs
echo "private key path: $SSL_TEST_PRIVATE_KEY"
echo "cert file path: $SSL_TEST_CERT_FILE"
cat "$SSL_TEST_PRIVATE_KEY" >"./$SERVER_FILES_DIR/certs/key.pem"
cat "$SSL_TEST_CERT_FILE" >"./$SERVER_FILES_DIR/certs/certificate.pem"
cat "$SSL_TEST_CERT_FILE" >"./$CLIENT_FILES_DIR/certificate.pem"

echo "Downloading demistomock and CommonServerPython from github."
curl --request GET https://raw.githubusercontent.com/demisto/content/master/Packs/Base/Scripts/CommonServerPython/CommonServerPython.py >./$CLIENT_FILES_DIR/CommonServerPython.py
curl --request GET https://raw.githubusercontent.com/demisto/content/master/Packs/ApiModules/Scripts/DemistoClassApiModule/DemistoClassApiModule.py >./$CLIENT_FILES_DIR/DemistoClassApiModule.py
curl --request GET https://raw.githubusercontent.com/demisto/content/master/Tests/demistomock/demistomock.py >./$CLIENT_FILES_DIR/demistomock.py

docker network create client_server_network

for file in "$NGINX_CONFS_PATH"/*; do
  nginx_conf_name=$(basename "$file")
  echo -e "================================================================="
  echo "Testing server image with custom nginx config $nginx_conf_name."
  echo -e "================================================================="
  server_image_name="server-image-$nginx_conf_name"

  if docker inspect "$server_image_name" &>/dev/null; then
    echo "Image $server_image_name exists in the cache."
  else
    echo "Image $server_image_name does not exist, building the image:"
    docker build --build-arg config_file="$file" -t "$server_image_name" -f "$SERVER_FILES_DIR/Dockerfile" .
  fi

  echo "Starting server $nginx_conf_name:"
  docker run --rm -d --name nginx-container --network client_server_network "$server_image_name"

  IFS=',' read -r -a docker_images <<<"${images_on_dockerhub}"
  for image in "${docker_images[@]}"; do
    docker pull "${image}"
    if ! docker inspect -f "{{.Config.Env}}" "${image}" | grep -q PYTHON_VERSION; then
      echo "Python is not installed in the Docker image: ${image}."
      continue
    fi
    echo -e "************************************************************"
    echo "Running client connection test for docker image: ${image}."
    echo "Running client with verify=False."
    if docker run --rm -v ./$CLIENT_FILES_DIR:/client -e REQUESTS_CA_BUNDLE=/client/certificate.pem --network client_server_network "${image}" sh -c "python /client/client.py"; then
      echo -e "${GREEN}Connection Test passes for nginx configuration: $nginx_conf_name and image name: $image, and verify=False${NC}"
    else
      echo -e "${RED}Connection Test failed for nginx configuration: $nginx_conf_name and image name: $image, and verify=False ${NC}"
      EXIT_CODE=1
    fi
    echo -e "************************************************************"
    echo "Running client with verify=True."
    if docker run --rm -v ./$CLIENT_FILES_DIR:/client -e REQUESTS_CA_BUNDLE=/client/certificate.pem --network client_server_network "${image}" sh -c "python /client/client.py -v"; then
      echo -e "${GREEN}Connection Test passes for nginx configuration: $nginx_conf_name and image name: $image, and verify=True${NC}"
    else
      echo -e "${RED}Connection Test failed for nginx configuration: $nginx_conf_name and image name: $image, and verify=True${NC}"
      EXIT_CODE=1
    fi
    echo -e "************************************************************"
    echo "Client test done."
  done
  echo -e "************************************************************"
  echo "Cleaning ..."
  docker stop nginx-container
done

docker network rm client_server_network

exit $EXIT_CODE
