# 1. Crear e ingresar al proyecto usando uv
uv init estimador-cag 
cd estimador-cag

uv python pin 3.13
uv venv --python 3.13

# 2. Agregar las dependencias solicitadas
uv add fastapi "uvicorn[standard]" pydantic-settings python-dotenv anthropic

# 3. Crear la estructura de directorios
mkdir app/routers 
mkdir app/services 
mkdir app/context

# 4. Crear los archivos dentro de app/
touch app/__init__.py app/main.py app/config.py
touch app/routers/__init__.py app/routers/estimations.py
touch app/services/__init__.py app/services/llm_service.py
touch app/context/__init__.py app/context/examples.py

# 5. Crear los archivos raíz del proyecto
touch .env .env.example .gitignore