#!/usr/bin/env bash
# Packs the mod for Nexus: every file committed to git, minus whatever .nexusignore
# matches (same syntax as .gitignore). Every file keeps its path, so the archive is laid out
# as the repository is, BAIN style:
#
#   00 Core/                  the mod
#   01 FBA Compatibility/ ... the optional patches: every top-level "NN Name" folder
#   fomod/                    the installer mod organisers show, which explains the patches
#   Sources/Tools/FBACompat/  the FBA builder, for rebuilding 01 with other settings
#
#   bash tools/build_nexus_zip.sh [output.zip]    (default: nexus-upload.zip)
set -euo pipefail

cd "$(dirname "$0")/.."
out="${1:-nexus-upload.zip}"
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
rm -f "$out"

files=$(comm -23 \
    <(git -c core.quotePath=false ls-files | sort) \
    <(git -c core.quotePath=false ls-files --cached --ignored --exclude-from=.nexusignore | sort))

if [ -z "$files" ]; then
    echo "Nothing to pack - check .nexusignore" >&2
    exit 1
fi

printf '%s\n' "$files" | zip -q -X "$out" -@
echo "Packed $(printf '%s\n' "$files" | wc -l) files into $out"
