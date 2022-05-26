#!/bin/sh

# this script is used to delete the instance once it is destroyed.
# this script run automatically when shutdown is called.
# google docs: https://cloud.google.com/compute/docs/shutdownscript

ZONE="$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone)"
NAME="$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)"
gcloud compute instances delete --zone="$ZONE" "$NAME" --quiet