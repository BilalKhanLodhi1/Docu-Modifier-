#!/bin/bash
# DocuCraft AI: one-step setup for macOS. Safe to run again after every update.
set -e
cd "$(dirname "$0")"

PY=""
for candidate in python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -z "$PY" ] && { echo "Python 3 is not installed. Get it from https://www.python.org/downloads/"; exit 1; }

if [ ! -d .venv ]; then
  echo "Creating the virtual environment with $($PY --version)..."
  "$PY" -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python packages (first run takes a few minutes)..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  echo "Creating .env..."
  cp .env.example .env
  SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
  sed -i '' "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$SECRET|" .env
  if command -v ollama >/dev/null 2>&1; then
    MODEL=$(ollama list 2>/dev/null | awk 'NR==2 {print $1}')
    if [ -n "$MODEL" ]; then
      sed -i '' "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$MODEL|" .env
      echo "Using your installed Ollama model: $MODEL"
    fi
  fi
else
  echo "Keeping your existing .env."
  if grep -q "^AI_CHUNK_CHARS=6000" .env; then
    sed -i '' "s|^AI_CHUNK_CHARS=6000|AI_CHUNK_CHARS=3000|" .env
    echo "Lowered AI_CHUNK_CHARS to 3000 for faster local rewrites."
  fi
  for key in AI_MAX_CALL_SECONDS; do
    grep -q "^$key=" .env || echo "$key=900" >> .env
  done
fi

echo "Preparing the database..."
python manage.py migrate --no-input -v 0

echo ""
python manage.py doctor --no-ai || true
echo ""
echo "Setup finished. Start DocuCraft with:  ./run.sh"
echo "Check the AI with a live test:          source .venv/bin/activate && python manage.py doctor"
