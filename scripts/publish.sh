#!/usr/bin/env bash
# scripts/publish.sh
# Publie le package sur PyPI en utilisant le token stocke dans .env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Charger le token depuis .env
if [ ! -f .env ]; then
    echo "❌ .env introuvable. Cree-le a partir de .env.example"
    exit 1
fi

# Extraire PYPI_TOKEN du .env
PYPI_TOKEN=$(grep -E '^PYPI_TOKEN=' .env | cut -d= -f2- | tr -d '\r')

if [ -z "$PYPI_TOKEN" ]; then
    echo "❌ PYPI_TOKEN non defini dans .env"
    exit 1
fi

# Nettoyer et builder
echo "📦 Nettoyage et build..."
rm -rf dist/ build/ *.egg-info src/*.egg-info
python -m build

# Uploader
echo "🚀 Upload sur PyPI..."
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" python -m twine upload dist/*

echo "✅ Publication terminee !"
