"""Prueba rápida: arranca el servidor MCP, lista sus herramientas y llama a
concat_version. Si imprime la versión de Concat, todo está bien configurado.

    python smoke_test.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
p = subprocess.Popen(
    [sys.executable, os.path.join(HERE, "concat_mcp.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", cwd=HERE)


def send(obj):
  p.stdin.write(json.dumps(obj) + "\n")
  p.stdin.flush()


def recv():
  line = p.stdout.readline()
  if not line:
    sys.exit("El servidor se cerró:\n" + p.stderr.read())
  return json.loads(line)


try:
  send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "smoke", "version": "0"}}})
  recv()
  send({"jsonrpc": "2.0", "method": "notifications/initialized"})

  send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
  print("Herramientas:", [t["name"] for t in recv()["result"]["tools"]])

  send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "concat_version", "arguments": {}}})
  result = recv()["result"]
  if result.get("isError"):
    sys.exit("Error: " + result["content"][0]["text"])
  print("Concat respondió:", result["content"][0]["text"])
finally:
  p.terminate()
