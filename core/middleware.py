from django.shortcuts import render
from core.models import SystemSetting


class MaintenanceModeMiddleware:
    """Blocks non-staff/non-superuser visitors when maintenance mode is active."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow static files, media, admin, login/logout, and system-admin endpoints
        exempt_prefixes = (
            '/static/',
            '/media/',
            '/admin/',
            '/system-admin/',
            '/login/',
            '/logout/',
            '/accounts/login/',
        )
        if any(request.path.startswith(prefix) for prefix in exempt_prefixes):
            return self.get_response(request)

        # Check user permissions
        if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
            return self.get_response(request)

        # Check maintenance setting
        setting = SystemSetting.get_settings()
        if setting.maintenance_mode:
            return render(
                request,
                'maintenance.html',
                {'setting': setting},
                status=503
            )

        return self.get_response(request)
