import os
import json
import secrets
import string
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from core.models import SystemSetting, BackupConfiguration, BackupRecord, Announcement
from core.services.backup_service import (
    execute_backup,
    restore_backup,
    get_storage_driver,
    determine_gfs_tier,
)

User = get_user_model()


def superuser_required(view_func):
    """Decorator ensuring only System Superusers can access system administration."""
    decorated_view = login_required(user_passes_test(lambda u: u.is_superuser)(view_func))
    return decorated_view


def _get_dir_size(path: str) -> int:
    """Calculates total size of a directory in bytes."""
    total = 0
    if not os.path.exists(path):
        return 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def _get_database_size() -> int:
    """Estimates database file or relation size in bytes."""
    db_engine = settings.DATABASES['default'].get('ENGINE', '')
    if 'sqlite3' in db_engine:
        db_path = str(settings.DATABASES['default'].get('NAME', ''))
        if os.path.exists(db_path):
            return os.path.getsize(db_path)
        return 0
    elif 'postgresql' in db_engine:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database());")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception:
            return 0
    return 0


# ---------------------------------------------------------------------------
# 1. System Diagnostics Dashboard
# ---------------------------------------------------------------------------

@superuser_required
def system_admin_dashboard(request):
    """Platform health, telemetry, diagnostics, and quick toggles."""
    setting = SystemSetting.get_settings()
    config = BackupConfiguration.get_config()

    # Database & media telemetry
    db_size = _get_database_size()
    media_dir = str(settings.MEDIA_ROOT) if hasattr(settings, 'MEDIA_ROOT') else os.path.join(str(settings.BASE_DIR), 'media')
    media_size = _get_dir_size(media_dir)
    backup_dir = os.path.join(str(settings.BASE_DIR), config.local_path or 'backups')
    backup_size = _get_dir_size(backup_dir)

    # Active sessions (not expired)
    active_sessions_count = Session.objects.filter(expire_date__gte=timezone.now()).count()

    # User breakdown
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    inactive_users = total_users - active_users
    role_breakdown = User.objects.values('role').annotate(count=Count('id')).order_by('-count')

    # Recent backups
    recent_backups = BackupRecord.objects.all().order_by('-created_at')[:5]

    context = {
        'setting': setting,
        'config': config,
        'db_size_mb': round(db_size / (1024 * 1024), 2),
        'media_size_mb': round(media_size / (1024 * 1024), 2),
        'backup_size_mb': round(backup_size / (1024 * 1024), 2),
        'active_sessions_count': active_sessions_count,
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'role_breakdown': role_breakdown,
        'recent_backups': recent_backups,
    }
    return render(request, 'admin/system_dashboard.html', context)


# ---------------------------------------------------------------------------
# 2. GFS Backup & Restore Console
# ---------------------------------------------------------------------------

@superuser_required
def system_admin_backups(request):
    """Console for GFS backup management, scheduled configurations, and audit trail."""
    config = BackupConfiguration.get_config()

    if request.method == 'POST' and 'update_config' in request.POST:
        config.is_enabled = request.POST.get('is_enabled') == 'on'
        config.storage_type = request.POST.get('storage_type', 'LOCAL')
        config.local_path = request.POST.get('local_path', 'backups').strip()
        config.backup_time = request.POST.get('backup_time', '02:00').strip()
        config.weekly_day = int(request.POST.get('weekly_day', 6))
        config.monthly_day = int(request.POST.get('monthly_day', 1))
        config.keep_daily = int(request.POST.get('keep_daily', 7))
        config.keep_weekly = int(request.POST.get('keep_weekly', 4))
        config.keep_monthly = int(request.POST.get('keep_monthly', 3))
        config.preserve_config_on_restore = request.POST.get('preserve_config_on_restore') == 'on'

        # S3
        config.s3_endpoint_url = request.POST.get('s3_endpoint_url', '').strip()
        config.s3_bucket = request.POST.get('s3_bucket', '').strip()
        config.s3_region = request.POST.get('s3_region', 'us-east-1').strip()
        config.s3_access_key = request.POST.get('s3_access_key', '').strip()
        config.s3_secret_key = request.POST.get('s3_secret_key', '').strip()
        config.s3_prefix = request.POST.get('s3_prefix', 'sportsball/').strip()

        # CIFS
        config.cifs_server = request.POST.get('cifs_server', '').strip()
        config.cifs_share = request.POST.get('cifs_share', '').strip()
        config.cifs_subpath = request.POST.get('cifs_subpath', '').strip()
        config.cifs_username = request.POST.get('cifs_username', '').strip()
        if request.POST.get('cifs_password'):
            config.cifs_password = request.POST.get('cifs_password').strip()
        config.cifs_domain = request.POST.get('cifs_domain', '').strip()

        # NFS
        config.nfs_server = request.POST.get('nfs_server', '').strip()
        config.nfs_export = request.POST.get('nfs_export', '').strip()
        config.nfs_subpath = request.POST.get('nfs_subpath', '').strip()

        # Security & Webhook
        config.encryption_passphrase = request.POST.get('encryption_passphrase', '').strip()
        config.webhook_url = request.POST.get('webhook_url', '').strip()

        config.save()
        messages.success(request, "Backup configuration saved successfully.")
        return redirect('system_admin_backups')

    # Records list with pagination
    records_list = BackupRecord.objects.all().order_by('-created_at')
    paginator = Paginator(records_list, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'config': config,
        'page_obj': page_obj,
    }
    return render(request, 'admin/backups.html', context)


@superuser_required
@require_POST
def backup_manual_trigger(request):
    """Executes an immediate manual backup snapshot."""
    config = BackupConfiguration.get_config()
    try:
        rec = execute_backup(tier='MANUAL', config=config)
        messages.success(request, f"Manual backup created successfully: {rec.filename} ({round(rec.file_size / 1024, 1)} KB)")
    except Exception as e:
        messages.error(request, f"Backup creation failed: {e}")
    return redirect('system_admin_backups')


@superuser_required
@require_POST
def backup_test_connection_api(request):
    """Tests connectivity to the active or requested backup storage target."""
    config = BackupConfiguration.get_config()
    storage_type = request.POST.get('storage_type', config.storage_type)
    
    # Create temporary clone of config if params are passed
    test_config = BackupConfiguration(
        storage_type=storage_type,
        local_path=request.POST.get('local_path', config.local_path),
        s3_endpoint_url=request.POST.get('s3_endpoint_url', config.s3_endpoint_url),
        s3_bucket=request.POST.get('s3_bucket', config.s3_bucket),
        s3_region=request.POST.get('s3_region', config.s3_region),
        s3_access_key=request.POST.get('s3_access_key', config.s3_access_key),
        s3_secret_key=request.POST.get('s3_secret_key', config.s3_secret_key),
        s3_prefix=request.POST.get('s3_prefix', config.s3_prefix),
        cifs_server=request.POST.get('cifs_server', config.cifs_server),
        cifs_share=request.POST.get('cifs_share', config.cifs_share),
        cifs_subpath=request.POST.get('cifs_subpath', config.cifs_subpath),
        cifs_username=request.POST.get('cifs_username', config.cifs_username),
        cifs_password=request.POST.get('cifs_password', config.cifs_password),
        cifs_domain=request.POST.get('cifs_domain', config.cifs_domain),
        nfs_server=request.POST.get('nfs_server', config.nfs_server),
        nfs_export=request.POST.get('nfs_export', config.nfs_export),
        nfs_subpath=request.POST.get('nfs_subpath', config.nfs_subpath),
    )
    
    driver = get_storage_driver(test_config)
    success, msg = driver.test_connection()
    return JsonResponse({'success': success, 'message': msg})


@superuser_required
def download_backup(request, backup_uuid):
    """Streams backup snapshot archive to the administrator's browser."""
    rec = get_object_or_404(BackupRecord, uuid=backup_uuid)
    config = BackupConfiguration.get_config()

    orig_storage = config.storage_type
    config.storage_type = rec.storage_type
    driver = get_storage_driver(config)
    config.storage_type = orig_storage

    try:
        data = driver.retrieve_file(rec.filename)
    except Exception as e:
        messages.error(request, f"Unable to read file from storage: {e}")
        return redirect('system_admin_backups')

    response = HttpResponse(data, content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{rec.filename}"'
    return response


@superuser_required
@require_POST
def restore_backup_view(request, backup_uuid):
    """Executes database restoration from an existing BackupRecord."""
    rec = get_object_or_404(BackupRecord, uuid=backup_uuid)
    passphrase = request.POST.get('passphrase', '').strip()

    try:
        restore_backup(rec, passphrase=passphrase)
        messages.success(request, f"Platform database successfully restored from snapshot '{rec.filename}'.")
    except Exception as e:
        messages.error(request, f"Database restoration failed: {e}")

    return redirect('system_admin_backups')


@superuser_required
@require_POST
def delete_backup(request, backup_uuid):
    """Deletes backup file from storage and removes its catalog record."""
    rec = get_object_or_404(BackupRecord, uuid=backup_uuid)
    config = BackupConfiguration.get_config()

    orig_storage = config.storage_type
    config.storage_type = rec.storage_type
    driver = get_storage_driver(config)
    config.storage_type = orig_storage

    try:
        driver.delete_file(rec.filename)
    except Exception as e:
        messages.warning(request, f"File deletion from storage reported: {e}")

    rec.delete()
    messages.success(request, f"Backup snapshot '{rec.filename}' removed.")
    return redirect('system_admin_backups')


# ---------------------------------------------------------------------------
# 3. User Account Controls (Password Reset, Deactivation)
# ---------------------------------------------------------------------------

@superuser_required
def system_admin_users(request):
    """Searchable, filterable list of all user accounts."""
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    status_filter = request.GET.get('status', '').strip()

    users = User.objects.all().select_related('church').order_by('-date_joined')

    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )

    if role_filter:
        users = users.filter(role=role_filter)

    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)

    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'roles': User.ROLE_CHOICES,
    }
    return render(request, 'admin/users.html', context)


@superuser_required
@require_POST
def admin_reset_user_password(request, user_id):
    """Resets user password and displays a temporary passphrase for administrative delivery."""
    target_user = get_object_or_404(User, id=user_id)

    # Generate random 10-char password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    temp_pass = ''.join(secrets.choice(alphabet) for _ in range(12))

    target_user.set_password(temp_pass)
    target_user.save()

    messages.success(
        request,
        f"Password for {target_user.display_name} ({target_user.username}) was reset to: {temp_pass}"
    )
    return redirect('system_admin_users')


@superuser_required
@require_POST
def admin_toggle_user_active(request, user_id):
    """1-Tap account activation/deactivation toggle."""
    target_user = get_object_or_404(User, id=user_id)

    if target_user.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own administrative account.")
        return redirect('system_admin_users')

    target_user.is_active = not target_user.is_active
    target_user.save()

    status_str = "activated" if target_user.is_active else "deactivated"
    messages.success(request, f"User account '{target_user.username}' has been {status_str}.")
    return redirect('system_admin_users')


# ---------------------------------------------------------------------------
# 4. System Emergency Banners & Maintenance Mode
# ---------------------------------------------------------------------------

@superuser_required
@require_POST
def admin_toggle_maintenance_mode(request):
    """1-Tap toggle for site maintenance mode."""
    setting = SystemSetting.get_settings()
    setting.maintenance_mode = not setting.maintenance_mode
    setting.save()

    status_str = "ENABLED (Visitors will see 503 Maintenance Page)" if setting.maintenance_mode else "DISABLED (Site is live for all visitors)"
    messages.success(request, f"Platform Maintenance Mode is now {status_str}.")
    return redirect(request.META.get('HTTP_REFERER', 'system_admin_dashboard'))


@superuser_required
@require_POST
def admin_update_emergency_banner(request):
    """Updates top alert banner content and toggles active status."""
    setting = SystemSetting.get_settings()
    setting.banner_message = request.POST.get('banner_message', '').strip()
    setting.banner_link = request.POST.get('banner_link', '').strip()
    setting.banner_active = request.POST.get('banner_active') == 'on'
    setting.save()

    messages.success(request, "Emergency alert banner settings updated.")
    return redirect(request.META.get('HTTP_REFERER', 'system_admin_dashboard'))
