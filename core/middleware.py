from __future__ import annotations
import zoneinfo
from django.shortcuts import render
from django.utils import timezone
from core.models import SystemSetting


class UserTimezoneMiddleware:
    """
    Activates the user's selected browser timezone per request.
    Reads 'sportsball_timezone' from cookie or session and applies it via django.utils.timezone.activate.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = request.COOKIES.get('sportsball_timezone') or request.session.get('django_timezone')
        if tzname and tzname != 'auto':
            try:
                timezone.activate(zoneinfo.ZoneInfo(tzname))
            except Exception:
                timezone.deactivate()
        else:
            timezone.deactivate()
        return self.get_response(request)


class MaintenanceModeMiddleware:
    """Blocks non-staff/non-superuser visitors when maintenance mode is active."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow static files, media, admin, login/logout, health probe, and system-admin endpoints
        exempt_prefixes = (
            '/static/',
            '/media/',
            '/admin/',
            '/system-admin/',
            '/login/',
            '/logout/',
            '/accounts/login/',
            '/healthz',
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
