# Concat MCP

Servidor [MCP](https://modelcontextprotocol.io) que deja a una IA controlar el
editor de video [Concat](https://github.com/jub0t/concat) (importar medios,
cortar, agregar títulos, exportar...).

Concat expone una API JSON-RPC 2.0 en **líneas JSON sobre TCP plano** (no es
WebSocket ni HTTP) en `127.0.0.1:7420`. Este script traduce las herramientas MCP
a esas llamadas. Docs de la API: https://concatenate.pages.dev/docs

## Requisitos

- Python 3.10+
- Concat abierto, con **Ajustes › Remoto** activado (muestra el puerto y el token)

## Instalación

```bash
pip install -r requirements.txt
```

1. Copiá `.env.example` a `.env`.
2. Pegá el token de **Ajustes › Remoto › Token** en `CONCAT_API_TOKEN`. Tiene 32
   caracteres hexadecimales: copialo completo.

## Probar

```bash
python smoke_test.py
```

Debe listar las herramientas e imprimir la versión de Concat.

## Usarlo con un cliente MCP

El `.mcp.json` de esta carpeta ya sirve para **Claude Code**: abrí la sesión
dentro de esta carpeta y aprobá el servidor `concat`. Para otros clientes
(Cursor, Claude Desktop, VS Code, Gemini CLI, Codex...) usá la misma entrada con
la ruta absoluta del script:

```json
{
  "mcpServers": {
    "concat": {
      "command": "python",
      "args": ["C:/ruta/a/concat_test_mcp/concat_mcp.py"]
    }
  }
}
```

En VS Code el archivo es `.vscode/mcp.json` y la clave es `servers`.

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `concat_version` | Versión de Concat, carpetas y capacidades |
| `concat_call` | Llama a cualquier método de la API (`method`, `params`) |
| `concat_project_create` | Crea y abre un proyecto (`location`, `name`, tamaño, fps) |
| `concat_project_open` | Abre un proyecto existente |
| `concat_project_get` | Estado del timeline: pistas, clips, medios |
| `concat_media_import` | Importa un archivo; `createdId` es el `mediaId` |
| `concat_edit_apply` | Aplica una edición (`{"op": ...}`), un paso de undo |
| `concat_export` | Renderiza a un archivo y espera a que termine |
| `concat_auto_subtitles` | Transcribe la voz con Whisper (local) y agrega los subtítulos como clips de texto, en un solo paso de undo |

Flujo típico: `concat_project_create` → `concat_media_import` →
`concat_edit_apply` (`addClipAtFirstFree`, `splitClips`, `addTextClip`...) →
`concat_export`. Referencia de comandos de edición:
https://concatenate.pages.dev/docs/api/edits

### Subtítulos automáticos

`concat_auto_subtitles(path, media_path, ...)` usa `faster-whisper` (modelo
`small` por defecto; la primera vez lo descarga) en CPU. Parámetros útiles:

- `timeline_start`: segundo del timeline donde empieza el clip.
- `source_start` / `source_end`: tramo del archivo a transcribir (0 = todo).
- `language`: `"es"`, `"en"`... (vacío = autodetectar).
- `font_size`, `color`, `offset_y`, `track_id`, `max_chars`, `model`.

Ejemplo: un clip que usa el tramo 25–45 s del archivo y está al inicio del
timeline → `timeline_start=0, source_start=25, source_end=45`. Se puede deshacer
con `edit.undo`. Whisper filtra los tramos sin voz (VAD), así que en música sin
canto no genera nada. El audio se decodifica con PyAV directamente porque
`faster-whisper` 1.2.x falla al abrir archivos con `av` 15 o superior.

## Cosas a tener en cuenta

- **Rutas:** la API solo escribe dentro de la carpeta de usuario
  (p. ej. `C:/Users/<vos>`). Un proyecto en `D:/` es rechazado (`refused`). Los
  videos a importar sí pueden estar en cualquier lado.
- **Barras:** usá `/` en las rutas dentro de los JSON.
- **Seguridad:** quien tenga el token puede leer cualquier archivo que tu usuario
  pueda leer, y la conexión no está cifrada. Concat escucha solo en `127.0.0.1`;
  no lo expongas a la red. No subas `.env` a git.
- **Token nuevo:** si pulsás **Nuevo token** en Concat, actualizá `.env`.

## Problemas comunes

| Síntoma | Causa |
|---|---|
| `Token inválido` | Token mal copiado (¿falta algún carácter?) o regenerado |
| `No pude conectar con Concat` | La app está cerrada o **Remoto** está desactivado |
| `notOpen` | Falta `project.open`/`project.create` antes de usar el proyecto |
| `refused ... outside where this API writes` | Proyecto fuera de la carpeta de usuario |
| `No module named 'mcp.server.mcpserver'` | Paquete `mcp` 1.x: instalá `mcp>=2` |
| Nada funciona y hay un `mcp.py` en la carpeta | Ese archivo tapa al paquete `mcp`; renombralo |
