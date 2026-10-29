# Field Notes Raw

Append raw errors and context here as they happen. The human turns these into
`docs/FIELD_NOTES.md`. Never fabricate entries.

---

## 2026-10-29 — `mcp` 2.x breaks the PLAN's import path

Context: fresh `pip install mcp` on Windows, Python 3.11. Building `server/app.py`
exactly as PLAN.md §2 specifies (`from mcp.server.fastmcp import FastMCP`).

Raw error:

```
File "C:\Users\User\AppData\Local\Programs\Python\Python311\Lib\site-packages\mcp\server\fastmcp.py", line 16, in <module>
    raise ModuleNotFoundError(_MESSAGE, name=__name__)
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer
(from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver or pin 'mcp<2' to keep running v1 code.
```

Also seen in the same install: `pip install mcp` pulled `mcp-2.3.0` and
`starlette-1.10.0`, which conflicts with the environment's FastAPI
(`fastapi 0.115.6 requires starlette<0.42.0,>=0.40.0`).

What was tried: reinstalling with `pip install "mcp>=1.2,<2" "starlette>=0.37,<0.42"`
resolved to `mcp-1.30.0` + `starlette-0.41.3` and the import worked.

Fix applied: pinned `mcp>=1.2,<2` and `starlette>=0.37,<0.42` in `requirements.txt`
with a comment explaining why.

---

## 2026-10-29 — `pytest` dies on import of sklearn via nltk

Context: running `pytest` in the same global Python environment.

Raw error (tail):

```
File "sklearn\utils\murmurhash.pyx", line 1, in init sklearn.utils.murmurhash
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```

Cause: an unrelated third-party pytest plugin autoloads `nltk`, which imports
`sklearn`, which is built against a different numpy. Not a KudiDesk bug.

Workaround used for local runs:

```
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest -p pytest_asyncio.plugin
```

Result: `48 passed`. A clean virtualenv would avoid this entirely.
