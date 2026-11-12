# Estimador CAG

Servicio de estimación de proyectos software a partir de transcripciones de reuniones y documentación complementaria. Expone una API FastAPI con dos modos de uso: peticiones aisladas (`/api/v1/estimate`) y **sesiones multi-turno** (`/sessions`), que es el modo descrito en este documento. Un cliente Streamlit consume la API.

## Cómo se levanta

```powershell
uv sync
copy .env.example .env          # rellenar ANTHROPIC_API_KEY y el resto de variables
uv run uvicorn app.main:app --reload
uv run streamlit run app/streamlit_app.py
```

La API queda en `http://127.0.0.1:8000` y su documentación interactiva en `/docs`. El cliente lee la URL de la API de `ESTIMATOR_API_BASE_URL`.

## Cómo se ejecutan los tests

```powershell
uv run pytest tests/test_sessions_unit.py tests/test_sessions_api.py -v
uv run pytest -v                 # suite completa
```

- `tests/test_sessions_unit.py`: ventana deslizante, `ProjectMetadata`, extractor heurístico, adjuntos y plantilla del system prompt. No necesita red ni proveedor.
- `tests/test_sessions_api.py`: tests de integración con `httpx.AsyncClient` sobre la aplicación en memoria. El LLM se sustituye por un doble que graba los mensajes recibidos. Cubren la sesión de dos peticiones, el PDF que cambia la estimación y las 8 vueltas con el límite de `MAX_TURNS`.
- Los datos de prueba son sintéticos y están en `tests/sample_data.py`. El PDF de prueba se genera en memoria con `make_text_pdf`.

## Endpoints de sesión

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/sessions` | Crea una sesión y devuelve `{"session_id": "<uuid4>"}` (código 201). |
| `GET` | `/sessions/{session_id}` | Devuelve `project_metadata`, número de turnos y tamaño de la ventana. |
| `POST` | `/sessions/{session_id}/estimate` | `multipart/form-data` con `transcript` (obligatorio) y `attachments` (opcional, varios archivos). Devuelve `{"text", "prompt_version": "session-v1"}`. |

Formatos de adjunto aceptados: `.txt`, `.md` y `.pdf`, con un máximo de 5 MiB por archivo. Cualquier otro tipo responde 422.

## Camino elegido para los adjuntos: B (extracción de texto local)

Los adjuntos se convierten a texto dentro del servicio y se concatenan a la transcripción con un separador explícito:

```text
<transcripción>

--- attachment: requisitos.pdf ---
<texto extraído del PDF>
```

Motivos de la elección:

1. **Independiente del proveedor.** La ruta A exige una Files API concreta (OpenAI, Anthropic…) y que LiteLLM la soporte para cada modelo. Con la ruta B el mismo mensaje funciona con cualquier modelo que pasa por `LLMWrapper`.
2. **Testeable sin red.** El texto extraído es determinista, así que el test del PDF puede comprobar que el contenido llega al prompt sin llamar a ningún servicio externo.
3. **Caché coherente.** El texto del adjunto forma parte del mensaje de usuario, y por tanto de la clave de caché SHA-256. Cambiar un documento invalida la respuesta cacheada.
4. **Coste conocido.** El adjunto cuenta en los tokens de entrada como cualquier otro texto, y el límite de 5 MiB acota el tamaño.

La contrapartida es que los PDF escaneados (sin capa de texto) no se leen, porque no hay OCR. Esto se trataría como una mejora posterior.

## Sesiones, historial y metadatos

Cada sesión tiene dos piezas separadas, definidas en `app/services/sessions.py`:

- **`ConversationHistory`**: ventana deslizante de pares usuario+asistente. Con `MAX_TURNS = 6` (configurable por variable de entorno) se conservan los últimos 6 turnos. Al superar el límite se descartan los pares más antiguos enteros, así que la lista nunca empieza por un mensaje del asistente. El system prompt no se guarda aquí: se regenera en cada petición.
- **`ProjectMetadata`**: modelo Pydantic con `project_name`, `assumed_team_size`, `mentioned_technologies` y `agreed_scope`. Se inyecta en el system prompt dentro de un bloque `<project_metadata>`. Si la sesión está vacía (primera llamada), el bloque no aparece.

El system prompt se renderiza desde `app/prompts/session/v1/system.j2`. El mensaje enviado al modelo tiene la forma `[system, *historial, usuario]`.

Las sesiones viven en un diccionario en memoria del proceso protegido por un `Lock`. Es suficiente para un único proceso local. Al reiniciar se pierden, y varios workers no comparten sesiones. Esta limitación es intencionada en esta fase.

## Cómo se extrae `project_metadata`

Tras cada respuesta, `app/services/metadata_extractor.py` actualiza los metadatos con **heurística** (expresiones regulares y lectura de secciones), sin una segunda llamada al LLM.

Motivos de la elección:

- **Coste y latencia.** Una llamada extra por turno duplica el coste de cada mensaje y añade latencia visible en el chat. La heurística no cuesta nada.
- **Determinismo.** Con datos fijos, el resultado siempre es el mismo, así que los tests pueden comprobar valores exactos.
- **Formato controlado.** El system prompt pide una estructura fija (`## <nombre>`, `### Recommended team` con una viñeta por rol, `### Project summary`). Esa estructura hace fiables las señales que busca el extractor.

Reglas de fusión:

- `project_name`: se fija en el primer turno que lo menciona (etiqueta `Proyecto:` o primer encabezado `##` que no sea genérico) y no cambia después.
- `mentioned_technologies`: unión de las tecnologías de la lista conocida que aparecen en la transcripción y en la respuesta, sin duplicados.
- `assumed_team_size`: se cuenta el número de viñetas de la sección de equipo; una viñeta que empieza por un número cuenta como esas personas.
- `agreed_scope`: primer párrafo de la sección de resumen, si existe.

El coste de este enfoque es que una formulación inesperada del modelo puede dejar un campo vacío. En ese caso el campo conserva su valor anterior. Si la calidad de la extracción no basta, el siguiente paso sería el extractor con LLM, con un prompt que devuelva JSON validado con Pydantic.

## Documentación de código

Las funciones públicas de los módulos nuevos y modificados llevan docstrings en formato reST (`:param:`, `:returns:`, `:raises:`), pensadas para Sphinx con `autodoc`.

## Limitaciones conocidas

- Las sesiones no sobreviven a un reinicio del proceso.
- Los PDF escaneados no se leen (no hay OCR).
- `uv.lock` debe regenerarse con `uv lock` porque se añadieron `pypdf`, `python-multipart` y el grupo `dev` con `pytest`.
- La configuración heredada (`REDIS_URL`, `PRIMARY_MODEL`, `FALLBACK_MODEL`, `OPENAI_API_KEY`, `LLM_TIMEOUT`, `LLM_RETRIES`, `CACHE_TTL`) sigue sin declararse en `app/config.py`, tal como indica `proyecto.md`. Las llamadas reales a `get_llm_wrapper` fallarán hasta resolverlo; los tests sustituyen esa dependencia.
