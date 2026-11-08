"""
Access control mixins for core and system administration views.
"""

from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login


class SuperuserRequiredMixin(UserPassesTestMixin):
    """Restricts view access strictly to authenticated system superusers."""

    def test_func(self):
        return bool(self.request.user.is_authenticated and self.request.user.is_superuser)

    def handle_no_permission(self):
        return redirect_to_login(self.request.get_full_path(), self.get_login_url(), self.get_redirect_field_name())
