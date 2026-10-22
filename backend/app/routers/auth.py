"""Login, logout and session probe (AUTH-01, D-15, D-16).

JSON bodies only (`extra="forbid"`): a cross-site form post gets 422 (T-01-18).
"""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth import SESSION_VALUE, protected_router, verify_credentials

router = APIRouter(prefix="/api")
protected = protected_router()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(max_length=128)
    password: str = Field(max_length=1024)


@router.post("/login", status_code=204)
async def login(body: LoginRequest, request: Request) -> Response:
    settings = request.app.state.settings
    if not await verify_credentials(settings, body.username, body.password):
        raise HTTPException(status_code=401, detail="bad_credentials")
    # Fresh session on login: nothing from a previous one survives.
    request.session.clear()
    request.session["auth"] = dict(SESSION_VALUE)
    return Response(status_code=204)


@protected.get("/session")
async def session() -> dict[str, bool]:
    return {"logged_in": True}


@protected.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)
