#!/usr/bin/env bash
# One-time setup: create venv and install dependencies.
set -e

cd "$(dirname "$0")"

echo "Creating virtual environment…"
python3 -m venv .venv

echo "Activating and installing dependencies…"
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✓ Setup complete."
echo ""
echo "Before running, make sure Ollama is running and you have pulled:"
echo "  ollama pull nomic-embed-text      # embedding model"
echo "  ollama pull llama3.3:70b          # or whichever chat model you prefer"
echo ""
echo "To start the app:"
echo "  source .venv/bin/activate && python app.py"
