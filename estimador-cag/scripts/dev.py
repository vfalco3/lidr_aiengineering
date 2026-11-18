"""Arranca el estimador completo en local: Redis con Docker Compose y la API con uvicorn.

Uso, desde la raíz del proyecto::

    uv run python scripts/dev.py                 # Redis + API en http://127.0.0.1:8000
    uv run python scripts/dev.py --port 8080     # otro puerto
    uv run python scripts/dev.py --stop-redis    # al salir, para también el contenedor de Redis
    uv run python scripts/dev.py --no-redis      # no toca Docker (Redis ya está en marcha)

Pasos:

1. Comprueba que hay una clave de LLM (``ANTHROPIC_API_KEY`` u ``OPENAI_API_KEY``) en
   el entorno o en ``.env``. Sin ella, cada estimación fallaría con un 500.
2. Levanta Redis con ``docker compose up -d redis`` y espera a que responda ``PONG``.
3. Arranca uvicorn en primer plano. Ctrl+C lo detiene.

Redis sigue activo al salir, salvo que se pase ``--stop-redis``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

#: Raíz del proyecto: el directorio que contiene ``scripts/``.
ROOT = Path(__file__).resolve().parent.parent

#: Variables de entorno que proporcionan la clave de un proveedor de LLM.
KEY_NAMES: tuple[str, ...] = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")

#: Segundos máximos que se espera a que Redis responda.
REDIS_WAIT_SECONDS = 60


def parse_env_file(text: str) -> dict[str, str]:
    """Lee pares ``CLAVE=valor`` de un archivo ``.env`` sencillo.

    Ignora comentarios, líneas vacías y líneas sin ``=``. Quita comillas simples o dobles
    alrededor del valor.

    :param text: Contenido bruto del archivo ``.env``.
    :returns: Diccionario con las variables definidas. Los valores vacíos se conservan como ``""``.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def has_llm_key(variables: Mapping[str, str]) -> bool:
    """Indica si alguna clave de proveedor de LLM tiene valor no vacío.

    :param variables: Variables de entorno o de ``.env``.
    :returns: ``True`` si ``ANTHROPIC_API_KEY`` u ``OPENAI_API_KEY`` no están vacías.
    """
    return any(variables.get(name, "").strip() for name in KEY_NAMES)


def check_llm_key(root: Path, environ: Mapping[str, str]) -> bool:
    """Comprueba la clave de LLM en el entorno del proceso o en el ``.env`` del proyecto.

    La variable de entorno tiene prioridad sobre el archivo, igual que en ``pydantic-settings``.

    :param root: Raíz del proyecto, donde está el ``.env``.
    :param environ: Variables de entorno del proceso.
    :returns: ``True`` si hay al menos una clave no vacía.
    """
    env_file = root / ".env"
    file_values = parse_env_file(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    merged = {**file_values, **{k: v for k, v in environ.items() if k in KEY_NAMES}}
    return has_llm_key(merged)


def require_docker() -> None:
    """Comprueba que el comando ``docker`` existe en el PATH.

    :raises SystemExit: Con un mensaje claro si Docker no está instalado o no está en el PATH.
    """
    if shutil.which("docker") is None:
        raise SystemExit("No encuentro el comando 'docker'. Instala Docker Desktop y ábrelo, o usa --no-redis.")


def start_redis(root: Path) -> None:
    """Levanta el servicio ``redis`` del compose del proyecto en segundo plano.

    :param root: Raíz del proyecto, donde está ``docker-compose.yml``.
    :raises subprocess.CalledProcessError: Si ``docker compose`` falla.
    """
    subprocess.run(["docker", "compose", "up", "-d", "redis"], cwd=root, check=True)


def wait_for_redis(root: Path, timeout: int = REDIS_WAIT_SECONDS) -> None:
    """Espera a que Redis responda ``PONG`` dentro del contenedor.

    :param root: Raíz del proyecto.
    :param timeout: Segundos máximos de espera.
    :raises RuntimeError: Si Redis no responde dentro del plazo.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "ping"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "PONG" in result.stdout:
            return
        time.sleep(2)
    raise RuntimeError(f"Redis no respondió en {timeout} s. Revisa 'docker compose logs redis'.")


def stop_redis(root: Path) -> None:
    """Para el contenedor de Redis sin borrarlo ni su volumen.

    :param root: Raíz del proyecto.
    """
    subprocess.run(["docker", "compose", "stop", "redis"], cwd=root, check=False)


def build_uvicorn_command(port: int, reload: bool) -> list[str]:
    """Construye la orden de uvicorn.

    Sin recarga, el proceso no se reinicia al cambiar archivos. Esto importa porque el
    almacén de sesiones vive en memoria: un reinicio borra todas las sesiones y el
    harness recibe 404 a mitad de una ejecución.

    :param port: Puerto local de la API.
    :param reload: ``True`` para recargar automáticamente al cambiar código.
    :returns: Los argumentos para ``subprocess``.
    """
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if reload:
        command.append("--reload")
    return command


def run_api(root: Path, port: int, reload: bool = False) -> int:
    """Arranca uvicorn en primer plano.

    :param root: Raíz del proyecto; uvicorn se ejecuta desde aquí para encontrar ``app/``.
    :param port: Puerto local de la API.
    :param reload: ``True`` para recargar automáticamente al cambiar código.
    :returns: El código de salida de uvicorn.
    """
    return subprocess.call(build_uvicorn_command(port, reload), cwd=root)


def build_arg_parser() -> argparse.ArgumentParser:
    """Define los argumentos de línea de órdenes.

    :returns: El parser configurado.
    """
    parser = argparse.ArgumentParser(description="Arranca Redis (Docker) y la API del estimador.")
    parser.add_argument("--port", type=int, default=8000, help="Puerto de la API. Por defecto 8000.")
    parser.add_argument("--no-redis", action="store_true", help="No usar Docker; Redis ya está en marcha.")
    parser.add_argument("--stop-redis", action="store_true", help="Al salir, para el contenedor de Redis.")
    parser.add_argument("--reload", action="store_true", help="Recarga la API al cambiar código. Borra las sesiones en memoria.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: comprueba la configuración, levanta Redis y arranca la API.

    :param argv: Argumentos de línea de órdenes; ``None`` usa ``sys.argv``.
    :returns: 0 si la API terminó limpiamente, 1 si falta la clave de LLM.
    """
    args = build_arg_parser().parse_args(argv)

    if not check_llm_key(ROOT, os.environ):
        print("Falta ANTHROPIC_API_KEY (o OPENAI_API_KEY) en .env. Sin clave, las estimaciones fallan.", file=sys.stderr)
        return 1

    if not args.no_redis:
        require_docker()
        print("Levantando Redis con docker compose...")
        start_redis(ROOT)
        wait_for_redis(ROOT)
        print("Redis listo en localhost:6379.")

    print(f"API en http://127.0.0.1:{args.port} (Ctrl+C para detener).")
    try:
        return run_api(ROOT, args.port, reload=args.reload)
    except KeyboardInterrupt:
        return 0
    finally:
        if args.stop_redis and not args.no_redis:
            stop_redis(ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
