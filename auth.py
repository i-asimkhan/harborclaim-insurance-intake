"""
Two completely separate login mechanisms for HarborClaim's two roles.

Claimants sign in with Google (self-service -- anyone with a Google account
gets an account, first login creates it). Adjusters use a username and
password that only exist because someone ran storage.create_adjuster() by
hand; there is no "sign in with Google" path to the adjuster role at all, and
no sign-up form for it either. This mirrors the real-world fact that being an
adjuster requires a state license, not just an email address -- see
storage.py's module docstring.

Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (from a real OAuth app
registered in Google Cloud Console -- see README) and SESSION_SECRET_KEY
(any random string, used only to sign the session cookie) in the
environment or a local .env file. Both login mechanisms share the same
session cookie (different keys within it), so a browser can be signed in as
a claimant and an adjuster at once -- two independent identities, same
person, same tab, matching how one real employee could both file a personal
claim and separately review others' claims at work.
"""

import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import storage

router = APIRouter(prefix="/auth")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_current_user(request: Request) -> dict | None:
    """FastAPI dependency: the signed-in claimant, or None.

    Reads only the email out of the session and re-fetches the user record
    from storage every time, rather than trusting a stale copy in the
    cookie -- so a change on the storage side takes effect on the next
    request, not just the next login.
    """
    email = request.session.get("user_email")
    if not email:
        return None
    return storage.get_user(email)


def get_current_adjuster(request: Request) -> dict | None:
    """FastAPI dependency: the signed-in adjuster, or None.

    Entirely independent of get_current_user above -- this reads a different
    session key, set only by POST /adjuster/login after a real password
    check, never by the Google callback.
    """
    username = request.session.get("adjuster_username")
    if not username:
        return None
    return storage.get_adjuster(username)


@router.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email")
    name = userinfo.get("name")

    if not email:
        return RedirectResponse(url="/")

    storage.get_or_create_user(email, name)
    request.session["user_email"] = email
    storage.record_login_event("claimant", email, "login")
    return RedirectResponse(url="/")


@router.get("/logout")
def logout(request: Request):
    # Pop only this role's key -- request.session.clear() would also wipe an
    # independent adjuster session sharing the same cookie, which is exactly
    # the cross-contamination separation of duties is supposed to prevent.
    email = request.session.pop("user_email", None)
    if email:
        storage.record_login_event("claimant", email, "logout")
    return RedirectResponse(url="/")
