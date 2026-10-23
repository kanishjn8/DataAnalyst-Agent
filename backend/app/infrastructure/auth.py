import jwt

from ..models import ApiError


class Auth:
    def __init__(self, settings):
        self.settings = settings

    async def __call__(self, request):
        value = request.headers.get("authorization", "")
        if not value.startswith("Bearer "):
            raise ApiError("Sign in to continue.", 401)
        try:
            claims = jwt.decode(
                value[7:],
                self.settings.jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=self.settings.jwt_issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            if claims.get("role") != "authenticated":
                raise ValueError("Invalid role")
            from uuid import UUID

            request.state.is_guest = bool(claims.get("is_anonymous"))
            return str(UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ApiError("Your session expired. Sign in again.", 401) from None
