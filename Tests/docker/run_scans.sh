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

image_artifacts="$2"

if [ -z "${image_artifacts}" ]; then
  echo -e "${RED}Please provide the image artifacts file path as an argument. Exiting.${NC}"
  exit 1
fi

if [ ! -s "${pushed_images}" ] && [ ! -s "${image_artifacts}" ]; then
  echo -e "${YELLOW}Pushed images file and image artifacts file are empty, exiting without running the tests.${NC}"
  exit 0
fi

echo "Downloading twistcli"
curl -f -u $PRISMA_CONSOLE_USER:$PRISMA_CONSOLE_PASS "$PRISMA_CONSOLE_URL/api/$PRISMA_CONSOLE_API_VERSION/util/twistcli?project=$PRISMA_CONSOLE_TENANT" -o twistcli

chmod +x ./twistcli
./twistcli --version

echo "successfully installed twistcli"

images_on_dockerhub=""
if [ -s "${pushed_images}" ]; then
  images_on_dockerhub=$(cat $pushed_images | sed 's/,$//')

  IFS=',' read -a docker_images <<<"$images_on_dockerhub"
  for image in "${docker_images[@]}"; do
    echo "Calling docker pull for $image"
    docker pull $image
    echo "Finished pulling image"
  done
fi

loaded_dockers=""
if [ -s "${image_artifacts}" ]; then
  while IFS=',' read -r image_save; do
    echo "getting image from $image_save"
    image_name=$(gunzip "${image_save}" | docker load | awk '/Loaded image:/{print $3}')
    echo "successfully loaded docker image:${image_name}"
    loaded_dockers+="${image_name},"
  done <"${image_artifacts}"
fi

docker_images_str="${loaded_dockers}${images_on_dockerhub}"
echo "Going to process the following images $docker_images_str"

ARTIFACTS_FOLDER="${ARTIFACTS_FOLDER:-artifacts}"
if [[ ! -d "${ARTIFACTS_FOLDER}" ]]; then
  mkdir -p "${ARTIFACTS_FOLDER}"
fi

SCAN_RESULTS="${ARTIFACTS_FOLDER}/scan_results"
if [[ ! -d "${SCAN_RESULTS}" ]]; then
  mkdir -p "${SCAN_RESULTS}"
fi
chmod +w "${SCAN_RESULTS}"
echo "Scan results will be saved in ${SCAN_RESULTS}"

IFS=',' read -a docker_images <<<"${docker_images_str}"
for image in "${docker_images[@]}"; do
  file="$(sed 's/\//_/g' <<<"${image}")_results.json"
  echo "output file will be $file"
  echo "calling twistlock for $image"

  ./twistcli images scan \
    --user=${PRISMA_CONSOLE_USER} \
    --docker-address http://docker:2375 \
    --password=${PRISMA_CONSOLE_PASS} \
    --address=${PRISMA_CONSOLE_URL} \
    --project=${PRISMA_CONSOLE_TENANT} \
    --output-file="${SCAN_RESULTS}/${file}" \
    --details "${image}"
done
