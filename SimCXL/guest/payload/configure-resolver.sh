#!/usr/bin/env bash
# Arguments make this independently testable without touching the host resolver.
set -euo pipefail
source_file=$1
destination=$2
backup=$3
if [[ ( -e "$destination" || -L "$destination" ) && ! -e "$backup" && ! -L "$backup" ]]; then
    cp -a -- "$destination" "$backup"
fi
# Replace dangling symlinks too; never write through them into another file.
cp --remove-destination -- "$source_file" "$destination"
