#!/bin/bash

pack_names="$1"
IFS=',' read -r -a pack_name_array <<<"$pack_names"

updated_names=()

for name in "${pack_name_array[@]}"; do
  if [[ $name != Packs/* ]]; then
    name="Packs/$name"
  fi
  updated_names+=("$name")
done

final_result=$(
  IFS=','
  echo "${updated_names[*]}"
)

echo "$final_result"
