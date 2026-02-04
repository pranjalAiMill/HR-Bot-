import os
from flask import request, abort

from dotenv import load_dotenv

load_dotenv()  

EXPECTED_TOKEN = os.getenv("MCP_TOKEN")

def require_token():
    if not EXPECTED_TOKEN:
        abort(500, "MCP_TOKEN not configured")

    if request.headers.get("X-MCP-TOKEN") != EXPECTED_TOKEN:
        abort(403)
