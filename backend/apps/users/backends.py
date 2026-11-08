from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.users.models import User


class EmailOrPhoneBackend(ModelBackend):
    """Authenticate with an email or an E.164 phone number as identifier."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        identifier = username or kwargs.get("identifier") or kwargs.get("email")
        if not identifier or not password:
            return None
        try:
            user = User.objects.get_by_identifier(identifier)
        except User.DoesNotExist:
            # Run the hasher anyway to reduce timing differences.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
