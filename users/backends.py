from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate against settings.AUTH_USER_MODEL using either email or username.
    Enables zero-friction email-only logins for players while maintaining backwards
    compatibility for admin and test console usernames.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD) or kwargs.get('email')
        if not username or not password:
            return None

        username_clean = str(username).strip()
        prefix = username_clean.split('@')[0] if '@' in username_clean else username_clean

        user = UserModel.objects.filter(
            Q(email__iexact=username_clean) |
            Q(username__iexact=username_clean) |
            Q(username__iexact=prefix)
        ).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
