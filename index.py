import hashlib
import hmac
import os
from pathlib import Path
from urllib.parse import parse_qs

from starlette.middleware import Middleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.websockets import WebSocketClose
from streamlit.starlette import App

COOKIE_NAME = "dashboard_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60

LOGIN_PAGE = """<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRC Scouting</title>
<h1>FRC Scouting</h1>
<form method="post">
  <label>Password <input type="password" name="password" autofocus required></label>
  <button>Log in</button>
</form>
<p>{error}</p>
"""


def session_token(password: str) -> str:
    return hmac.new(password.encode(), b"dashboard-session", hashlib.sha256).hexdigest()


def matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


class PasswordGate:
    """Blocks every page, file, and websocket until the visitor logs in. With no password set, nobody gets in."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        password = os.getenv("DASHBOARD_PASSWORD", "")
        cookie = HTTPConnection(scope).cookies.get(COOKIE_NAME, "")
        if password and matches(cookie, session_token(password)):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await WebSocketClose()(scope, receive, send)
            return

        request = Request(scope, receive)
        error = ""
        if request.method == "POST":
            form = parse_qs((await request.body()).decode(errors="replace"))
            if password and matches(form.get("password", [""])[0], password):
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(COOKIE_NAME, session_token(password), max_age=COOKIE_MAX_AGE,
                                    httponly=True, secure=True, samesite="lax")
                await response(scope, receive, send)
                return
            error = "Wrong password."
        await HTMLResponse(LOGIN_PAGE.format(error=error), status_code=401)(scope, receive, send)


# Vercel entry point. Locally, use `streamlit run dashboard/app.py` instead, which needs no password.
app = App(Path(__file__).resolve().parent / "dashboard" / "app.py", middleware=[Middleware(PasswordGate)])
