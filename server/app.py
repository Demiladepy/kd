import os
import json
from typing import Any

from dotenv import load_dotenv

# Local runs read .env; on Render the dashboard provides the real env vars and
# load_dotenv() is a no-op when no file is present.
load_dotenv()

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .tools import KudiDeskTools


def _transport_security() -> TransportSecuritySettings:
    """Host/Origin validation for the MCP transport.

    The SDK defaults to DNS-rebinding protection with an *empty* allowlist,
    which rejects every Host header that is not an exact match - so any public
    hostname (Render, a tunnel) gets 421 Misdirected Request. "*" is not a
    wildcard either; only exact values and "host:*" patterns match.

    Set MCP_ALLOWED_HOSTS="kudidesk.onrender.com,localhost:8000" to turn it on
    with explicit hosts. Left unset, we disable it: the endpoint is already
    gated by the bearer token, so a browser on this machine gains nothing.
    """
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=hosts,
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "kudidesk",
    stateless_http=True,
    json_response=True,
    transport_security=_transport_security(),
)
tools = KudiDeskTools()

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)


class RequestForensicsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Log all requests for forensics
        try:
            headers = dict(request.headers)
            if "authorization" in headers:
                headers["authorization"] = "Bearer [REDACTED]"
            if "Authorization" in headers:
                headers["Authorization"] = "Bearer [REDACTED]"
            log_entry = {
                "path": path,
                "method": request.method,
                "headers": headers
            }
            # Try to read body for JSON-RPC
            if request.method == "POST":
                body = await request.body()
                try:
                    data = json.loads(body)
                    log_entry["jsonrpc"] = data.get("jsonrpc")
                    log_entry["method"] = data.get("method")
                    if "params" in data:
                        log_entry["params"] = data["params"]
                        # Check for meta
                        if isinstance(data.get("params"), dict) and "_meta" in data["params"]:
                            log_entry["params_meta"] = data["params"]["_meta"]
                except:
                    pass
                # Need to reconstruct request body
                async def receive():
                    return {"type": "http.request", "body": body}
                request._receive = receive
            with open("logs/inbound.jsonl", "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            pass
        return await call_next(request)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ["/health", "/paid"]:
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == self.token:
                return await call_next(request)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"ok": True})


@mcp.custom_route("/paid", methods=["GET"])
async def paid(request: Request):
    html = """
    <html>
        <head><title>Payment Received</title></head>
        <body>
            <h1>Payment received</h1>
            <p>Go back to WhatsApp and tell KudiDesk you've paid.</p>
        </body>
    </html>
    """
    return HTMLResponse(html)


@mcp.tool()
async def start_session(account_code: str, pin: str) -> dict:
    """Start a session with account code and PIN"""
    return await tools.start_session(account_code, pin)


@mcp.tool()
async def create_quote(session_token: str, supplier_label: str, usd_amount: str, invoice_ref: str) -> dict:
    """Create a quote for a supplier payment"""
    return await tools.create_quote(session_token, supplier_label, usd_amount, invoice_ref)


@mcp.tool()
async def create_naira_payment(session_token: str, quote_id: str) -> dict:
    """Create Paystack payment link"""
    return await tools.create_naira_payment(session_token, quote_id)


@mcp.tool()
async def verify_and_settle(session_token: str, quote_id: str) -> dict:
    """Verify payment and settle on-chain"""
    return await tools.verify_and_settle(session_token, quote_id)


app = mcp.streamable_http_app()
bearer_token = os.getenv("MCP_BEARER_TOKEN", "change-me-long-random")
app.add_middleware(BearerAuthMiddleware, token=bearer_token)
app.add_middleware(RequestForensicsMiddleware)
