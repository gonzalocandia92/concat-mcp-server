"""Servidor MCP (stdio) para Concat.

Puente hacia el JSON-RPC de Concat (líneas JSON sobre TCP, ver
https://concatenate.pages.dev/docs/transports/json-rpc). Requiere la app abierta
con Ajustes > Remoto activado. El token se lee de CONCAT_API_TOKEN (.env).
"""
import json
import os
import socket
import threading

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

HOST = os.getenv("CONCAT_HOST", "127.0.0.1")
PORT = int(os.getenv("CONCAT_PORT", "7420"))
TOKEN = os.environ["CONCAT_API_TOKEN"]

mcp = MCPServer("concat")


class ConcatError(Exception):
  pass


class Connection:
  """Una conexión autenticada y reutilizada; se reabre si se cae."""

  def __init__(self):
    self.lock = threading.Lock()
    self.sock = None
    self.file = None
    self.next_id = 1
    self.events = []

  def _open(self):
    self.sock = socket.create_connection((HOST, PORT), timeout=60)
    self.file = self.sock.makefile("rw", encoding="utf-8", newline="\n")
    self.events = []
    self._send({"jsonrpc": "2.0", "id": 0, "method": "auth",
                "params": {"token": TOKEN}})
    if "error" in self._read():
      self.close()
      raise ConcatError("Token inválido (revisá CONCAT_API_TOKEN en .env)")

  def close(self):
    try:
      if self.sock:
        self.sock.close()
    finally:
      self.sock = self.file = None

  def _send(self, obj):
    self.file.write(json.dumps(obj) + "\n")
    self.file.flush()

  def _read(self):
    line = self.file.readline()
    if not line:
      raise ConnectionError("Concat cerró la conexión")
    return json.loads(line)

  def _request(self, method, params):
    req_id = self.next_id
    self.next_id += 1
    self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                "params": params})
    while True:
      msg = self._read()
      if msg.get("id") == req_id:
        if "error" in msg:
          err = msg["error"]
          raise ConcatError(
              f"{(err.get('data') or {}).get('code')}: {err.get('message')}")
        return msg["result"]
      self.events.append(msg)

  def call(self, method, params):
    with self.lock:
      for attempt in (0, 1):
        try:
          if self.sock is None:
            self._open()
          result = self._request(method, params)
          if method == "export.run":
            result = {**result, **self._wait_export(result["job"])}
          return result
        except (OSError, ConnectionError):
          self.close()
          if attempt:
            raise ConcatError(
                f"No pude conectar con Concat en {HOST}:{PORT}. ¿Está abierta "
                "la app con Ajustes > Remoto activado?")

  def _wait_export(self, job):
    self.sock.settimeout(3600)
    while True:
      for i, ev in enumerate(self.events):
        if ev.get("method") in ("export.done", "export.failed") \
                and ev["params"].get("job") == job:
          self.events.pop(i)
          return {"event": ev["method"], "details": ev["params"]}
      self.events.append(self._read())


conn = Connection()


def call(method: str, params: dict | None = None) -> dict:
  try:
    return conn.call(method, params or {})
  except ConcatError as e:
    raise RuntimeError(str(e))


@mcp.tool()
def concat_version() -> dict:
  """Versión de Concat, carpetas y capacidades. Llamar primero."""
  return call("version")


@mcp.tool()
def concat_call(method: str, params: dict | None = None) -> dict:
  """Llama a cualquier método JSON-RPC de Concat.

  Métodos: version, project.create|open|close|list|get|document|save|setVideo,
  edit.apply|undo|redo, media.probe|import, catalogue.list, template.list|
  instantiate|save, export.run|cancel, preview.frame. Los métodos de proyecto
  llevan `path` (carpeta del proyecto, ya abierto con project.open/create).
  Referencia: https://concatenate.pages.dev/docs/api/methods
  """
  return call(method, params)


@mcp.tool()
def concat_project_create(location: str, name: str,
                          width: int = 1920, height: int = 1080,
                          fps: int = 30) -> dict:
  """Crea y abre un proyecto en `location/name`.

  La API solo escribe dentro de la carpeta de usuario (C:/Users/Gonzalo): un
  `location` en otro disco (p. ej. D:/) es rechazado con `refused`.
  """
  return call("project.create", {
      "location": location, "name": name,
      "video": {"width": width, "height": height, "rateNum": fps,
                "rateDen": 1}})


@mcp.tool()
def concat_project_open(path: str) -> dict:
  """Abre un proyecto existente (carpeta) y devuelve su estado."""
  return call("project.open", {"path": path})


@mcp.tool()
def concat_project_get(path: str) -> dict:
  """Estado actual (timeline, pistas, clips, medios) de un proyecto abierto."""
  return call("project.get", {"path": path})


@mcp.tool()
def concat_media_import(path: str, file: str) -> dict:
  """Importa un archivo de video/audio/imagen al bin. `createdId` = mediaId."""
  return call("media.import", {"path": path, "file": file})


_whisper_models = {}


def _transcribe(media_path, model_name, language, source_start, source_end):
  """Devuelve [(inicio, fin, texto)] de las palabras reconocidas, en segundos
  del archivo original."""
  from faster_whisper import WhisperModel  # import perezoso: es pesado

  model = _whisper_models.get(model_name)
  if model is None:
    model = _whisper_models[model_name] = WhisperModel(
        model_name, device="cpu", compute_type="int8")
  audio = _load_audio(media_path, source_start, source_end)
  segments, _ = model.transcribe(
      audio, language=language, word_timestamps=True, vad_filter=True)
  # los tiempos de Whisper son relativos al tramo: se devuelven absolutos
  return [(float(source_start + w.start), float(source_start + w.end),
           w.word.strip())
          for seg in segments for w in (seg.words or []) if w.word.strip()]


def _load_audio(path, start, end, rate=16000):
  """Audio mono float32 a 16 kHz del tramo [start, end] (end 0 = hasta el final).

  Se decodifica con PyAV directamente: faster-whisper 1.2.x falla al abrir
  archivos con versiones nuevas de PyAV (`metadata_errors`).
  """
  import av
  import numpy as np

  chunks = []
  with av.open(path) as container:
    resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
    for frame in container.decode(audio=0):
      for out in resampler.resample(frame):
        chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
      chunks.append(out.to_ndarray().reshape(-1))
  samples = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
  a = int(start * rate)
  b = int(end * rate) if end else len(samples)
  return samples[a:b]


def _group_words(words, max_chars, max_seconds):
  """Agrupa palabras en líneas cortas de subtítulo."""
  lines, cur = [], []
  for w in words:
    text = " ".join(x[2] for x in cur + [w])
    if cur and (len(text) > max_chars or w[1] - cur[0][0] > max_seconds):
      lines.append(cur)
      cur = []
    cur.append(w)
    if w[2][-1] in ".?!" and len(cur) > 1:
      lines.append(cur)
      cur = []
  if cur:
    lines.append(cur)
  return [(ln[0][0], ln[-1][1], " ".join(x[2] for x in ln)) for ln in lines]


@mcp.tool()
def concat_auto_subtitles(path: str, media_path: str,
                          timeline_start: float = 0.0,
                          source_start: float = 0.0,
                          source_end: float = 0.0,
                          language: str | None = None,
                          font_size: float = 0.045, color: str = "#ffffff",
                          offset_y: float = 0.3, track_id: str | None = None,
                          max_chars: int = 32, model: str = "small") -> dict:
  """Transcribe la voz con Whisper (faster-whisper, local) y agrega los
  subtítulos como clips de texto en el timeline, en un solo paso de undo.

  Args:
    path: carpeta del proyecto (ya abierto).
    media_path: archivo de audio/video a transcribir (el mismo del clip).
    timeline_start: segundo del timeline donde empieza ese clip.
    source_start / source_end: tramo del archivo a transcribir (0 = todo).
    language: "es", "en"... (None = autodetectar).
    font_size, color, offset_y: estilo y posición vertical (ver addTextClip).
    track_id: pista de destino (None = la que elija Concat).
    max_chars: largo máximo de cada línea de subtítulo.
    model: modelo de Whisper (tiny, base, small, medium...).
  Devuelve la cantidad de subtítulos y el texto transcripto.
  """
  try:
    words = _transcribe(media_path, model, language, source_start, source_end)
  except Exception as e:
    raise RuntimeError(f"Falló la transcripción: {e}")
  if not words:
    return {"subtitles": 0, "note": "No se detectó voz."}

  commands = []
  for start, end, text in _group_words(words, max_chars, max_seconds=4.0):
    cmd = {
        "op": "addTextClip",
        "start": round(timeline_start + start - source_start, 3),
        "duration": round(max(end - start, 0.3), 3),
        "style": {"content": text, "fontSize": font_size, "color": color},
        "offsetY": offset_y,
    }
    if track_id:
      cmd["trackId"] = track_id
    commands.append(cmd)
  view = call("edit.apply", {"path": path,
                             "command": {"op": "batch", "commands": commands}})
  return {"subtitles": len(commands),
          "text": [c["style"]["content"] for c in commands],
          "canUndo": view.get("canUndo")}


@mcp.tool()
def concat_edit_apply(path: str, command: dict) -> dict:
  """Aplica un comando de edición ({"op": ...}) como un paso de undo.

  Ops: addClip{mediaId,trackId,start}, addClipAtFirstFree{mediaId,start},
  addTextClip{start,duration,style:{content,fontSize,color},offsetY},
  moveClips, trimClip{clipId,edge,delta}, splitClips{clipIds,time},
  removeClips{clipIds}, updateClip{clipId,patch}, setClipTransform,
  setClipSpeed, addTrack, batch{commands:[...]}, entre otros.
  Referencia: https://concatenate.pages.dev/docs/api/edits
  """
  return call("edit.apply", {"path": path, "command": command})


@mcp.tool()
def concat_export(path: str, output: str, codec: str = "h264",
                  crf: int = 20) -> dict:
  """Renderiza el timeline a `output` y espera a que termine."""
  return call("export.run", {"path": path, "output": output, "codec": codec,
                             "crf": crf})


if __name__ == "__main__":
  mcp.run()
