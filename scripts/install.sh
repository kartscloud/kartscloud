#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JARVIS_HOME="${HOME}/.jarvis"

mkdir -p "${JARVIS_HOME}"
mkdir -p "${JARVIS_HOME}/briefs"

if [ ! -f "${JARVIS_HOME}/.env" ]; then
    cp "${REPO_ROOT}/.env.example" "${JARVIS_HOME}/.env"
    echo "seeded ${JARVIS_HOME}/.env from .env.example"
    echo "fill in ANTHROPIC_API_KEY and CANVAS_TOKEN before running jarvis"
else
    echo "${JARVIS_HOME}/.env already exists, left alone"
fi

pip install -e "${REPO_ROOT}"

echo
echo "done. try: jarvis --help"
