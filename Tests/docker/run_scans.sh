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
.
images_to_curl="$2"

echo "Downloading twistcli"
curl -f -u $PRISMA_CONSOLE_USER:$PRISMA_CONSOLE_PASS "$PRISMA_CONSOLE_URL/api/$PRISMA_CONSOLE_API_VERSION/util/twistcli?project=$PRISMA_CONSOLE_TENANT" -o twistcli

chmod +x ./twistcli
./twistcli --version

echo "successfully installed twistcli"
images_on_dockerhub=$(cat $pushed_images | sed 's/,$//')

mkdir -p scan_results
chmod +w scan_results

IFS=',' read -a docker_images <<<"$images_on_dockerhub"
for image in "${docker_images[@]}"; do
  echo "Calling docker pull for $image"
  docker pull $image
  echo "Finished pulling image"
done

loaded_dockers=""

while IFS= read -r url; do
  echo "getting image from $url"
  image_name=$(curl -L "$url" | gunzip | docker load | awk '/Loaded image:/{print $3}')
  echo "successfully loaded docker image $image_name"
  loaded_dockers+="$image_name,"
done <"$images_to_curl"

docker_images_str="${loaded_dockers}${images_on_dockerhub}"
echo "Going to process the following images $docker_images_str"

IFS=',' read -a docker_images <<<"$docker_images_str"
for image in "${docker_images[@]}"; do
  file="$(sed 's/\//_/g' <<<$image)_results.json"
  echo "output file will be $file"
  echo "calling twistlock for $image"

  ./twistcli images scan \
    --user=$PRISMA_CONSOLE_USER \
    --docker-address http://docker:2375 \
    --password=$PRISMA_CONSOLE_PASS \
    --address=$PRISMA_CONSOLE_URL \
    --project=$PRISMA_CONSOLE_TENANT \
    --output-file="scan_results/$file" \
    --details $image
done
