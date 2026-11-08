"""Refresh token in an HttpOnly cookie for the Web client (OPEN_QUESTIONS Q26).

The Web client opts in with the `X-FMS-Token-Transport: cookie` header: the refresh token
is then never exposed to JavaScript (no theft through an injected script). Mobile apps
keep the token in the body and store it in the system keychain.

Cross-site requests cannot use the cookie: it is `SameSite=Strict`, limited to the
authentication endpoints, and those endpoints require the custom header, which a
cross-origin page cannot send without a CORS preflight (no CORS is configured).
"""

from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response

COOKIE_NAME = "fms_refresh"
COOKIE_PATH = "/api/v1/auth/"
TRANSPORT_HEADER = "X-FMS-Token-Transport"


def wants_cookie(request: Request) -> bool:
    return request.headers.get(TRANSPORT_HEADER, "").lower() == "cookie"


def refresh_from_cookie(request: Request) -> str | None:
    return request.COOKIES.get(COOKIE_NAME) or None


def move_refresh_to_cookie(response: Response) -> Response:
    """Take the refresh token out of the JSON body and put it in the cookie."""
    data = response.data if isinstance(response.data, dict) else {}
    token = data.pop("refresh", None)
    if token:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            path=COOKIE_PATH,
            secure=settings.FMS_REFRESH_COOKIE_SECURE,
            httponly=True,
            samesite="Strict",
        )
    return response


def clear_refresh_cookie(response: Response) -> Response:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, samesite="Strict")
    return response
