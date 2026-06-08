#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 path/to/remark_multi.json path/to/backbones_dir path/to/standardized_pdb_dir"
  exit 1
fi

remark_json_file="$1"
backbones_dir="$2"
standardized_pdb_dir="$3"

mkdir -p "${standardized_pdb_dir}"

# Loop over all entries in the JSON, base64 encoded
jq -r 'to_entries[] | @base64' "$remark_json_file" | while read -r entry; do
    decoded=$(echo "$entry" | base64 --decode)
    key=$(echo "$decoded" | jq -r '.key')
    key_base=$(basename "${key%.pdb}")
    value=$(echo "$decoded" | jq -r '.value')

    files=$(ls "${backbones_dir}/${key_base}_"*.pdb 2>/dev/null || true)

    if [ -z "$files" ]; then
        echo "Error: No files found for: ${key_base}_*.pdb" >&2
        exit 1
    fi

    for file in $files; do
        if [[ -f "$file" ]]; then
            echo "Prepending remarks to: $file"
            filename=$(basename "$file")
            new_file="${standardized_pdb_dir}/${filename}"
            { echo -e "$value"; cat "$file"; } > "$new_file"
        fi
    done
done
