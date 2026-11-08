from datetime import timedelta
from django.utils import timezone
from core.models import Announcement, SystemSetting


def announcement_alerts(request):
    """Context processor providing new/recent announcement count for sidebar alert badges."""
    if not request.user.is_authenticated:
        return {'new_announcements_count': 0}

    cutoff = timezone.now() - timedelta(days=7)
    recent_count = Announcement.objects.filter(created_at__gte=cutoff).count()
    return {
        'new_announcements_count': recent_count,
    }


def emergency_banner(request):
    """Context processor providing active emergency banners across all templates."""
    try:
        setting = SystemSetting.get_settings()
        if setting.banner_active and setting.banner_message:
            return {
                'active_banner': {
                    'title': setting.banner_message,
                    'link': setting.banner_link,
                    'type': 'system',
                }
            }
        announcement_banner = Announcement.objects.filter(is_banner=True, banner_active=True).order_by('-created_at').first()
        if announcement_banner:
            return {
                'active_banner': {
                    'title': announcement_banner.title,
                    'link': f"/announcements/{announcement_banner.pk}/",
                    'type': 'announcement',
                    'league': announcement_banner.league,
                }
            }
    except Exception:
        pass
    return {'active_banner': None}
