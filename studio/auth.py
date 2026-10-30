from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        User = get_user_model()
        try:
            user = User.objects.get(username__iexact=username.strip())
        except User.DoesNotExist:
            User().set_password(password)
            return None
        return user if user.check_password(password) and self.user_can_authenticate(user) else None
