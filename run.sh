#!/bin/bash
# Start DocuCraft AI at http://127.0.0.1:8000
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }
source .venv/bin/activate
if lsof -ti :8000 >/dev/null 2>&1; then
  echo "Port 8000 is in use (probably an older DocuCraft server). Stopping it..."
  lsof -ti :8000 | xargs kill 2>/dev/null || true
  sleep 1
fi
if command -v ollama >/dev/null 2>&1 && ! curl -s -o /dev/null http://localhost:11434/api/tags; then
  echo "Starting Ollama in the background..."
  (ollama serve >/dev/null 2>&1 &)
  sleep 3
fi
python manage.py migrate --no-input -v 0
echo "DocuCraft is running at http://127.0.0.1:8000  (press Ctrl+C to stop)"
python manage.py runserver 127.0.0.1:8000
