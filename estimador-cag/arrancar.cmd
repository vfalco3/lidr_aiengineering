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

echo API en http://127.0.0.1:8080 (docs en /docs)
echo Interfaz Streamlit en http://localhost:8501

# para generar csv
uv run python -m evals.stress.run --http http://localhost:8080 --scenarios growing,pivot,contradiction --attachment-sizes 0,5,20,50,100 --repeats 3 --output evals/stress/results.csv

#para  generar md
uv run python -m evals.stress.report --csv evals/stress/results.csv --output evals/stress/REPORT.md
