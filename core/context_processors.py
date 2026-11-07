from datetime import timedelta
from django.utils import timezone
from core.models import Announcement


def announcement_alerts(request):
    """Context processor providing new/recent announcement count for sidebar alert badges."""
    if not request.user.is_authenticated:
        return {'new_announcements_count': 0}

    cutoff = timezone.now() - timedelta(days=7)
    recent_count = Announcement.objects.filter(created_at__gte=cutoff).count()
    return {
        'new_announcements_count': recent_count,
    }
