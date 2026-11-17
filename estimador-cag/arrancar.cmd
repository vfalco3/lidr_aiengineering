@echo off
cd /d "%~dp0"

if not exist .env (
  copy .env.example .env >nul
  echo Se ha creado .env. Rellena ANTHROPIC_API_KEY y vuelve a ejecutar este archivo.
  pause
)

call uv sync
if errorlevel 1 (
  echo uv sync ha fallado.
  pause
  exit /b 1
)
uv run python scripts/dev.py --port 8080

echo API en http://127.0.0.1:8000 (docs en /docs)
echo Interfaz Streamlit en http://localhost:8501
