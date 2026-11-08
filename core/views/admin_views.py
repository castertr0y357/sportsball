"""
System diagnostics, telemetry, user management, and automated GFS backup views.
All views are implemented as Class-Based Views restricted to Superusers.
"""

from __future__ import annotations
import os
import json
import secrets
import string
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.generic import View

from core.models import SystemSetting, BackupConfiguration, BackupRecord, Announcement
from core.services.backup_service import (
    execute_backup,
    restore_backup,
    get_storage_driver,
    determine_gfs_tier,
)
from core.views.mixins import SuperuserRequiredMixin

User = get_user_model()


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


class SystemAdminDashboardView(SuperuserRequiredMixin, View):
    """Platform health, telemetry, diagnostics, and quick toggles."""

    def get(self, request):
        setting = SystemSetting.get_settings()
        config = BackupConfiguration.get_config()

        db_size = _get_database_size()
        media_dir = str(settings.MEDIA_ROOT) if hasattr(settings, 'MEDIA_ROOT') else os.path.join(str(settings.BASE_DIR), 'media')
        media_size = _get_dir_size(media_dir)
        backup_dir = os.path.join(str(settings.BASE_DIR), config.local_path or 'backups')
        backup_size = _get_dir_size(backup_dir)

        active_sessions_count = Session.objects.filter(expire_date__gte=timezone.now()).count()
        total_users = User.objects.count()
        active_users = User.objects.filter(is_active=True).count()
        inactive_users = total_users - active_users
        role_breakdown = User.objects.values('role').annotate(count=Count('id')).order_by('-count')

        recent_backups = BackupRecord.objects.all().order_by('-created_at')[:5]

        context = {
            'setting': setting,
            'config': config,
            'db_size': db_size,
            'media_size': media_size,
            'backup_size': backup_size,
            'active_sessions_count': active_sessions_count,
            'total_users': total_users,
            'active_users': active_users,
            'inactive_users': inactive_users,
            'role_breakdown': role_breakdown,
            'recent_backups': recent_backups,
            'current_time': timezone.now(),
        }
        return render(request, 'admin/system_dashboard.html', context)


class SystemAdminBackupsView(SuperuserRequiredMixin, View):
    """Manage automated schedules, cloud credentials, and snapshot repository."""

    def get(self, request):
        config = BackupConfiguration.get_config()
        backups = BackupRecord.objects.all().order_by('-created_at')

        tier_filter = request.GET.get('tier')
        if tier_filter:
            backups = backups.filter(tier=tier_filter)

        total_backups_count = BackupRecord.objects.count()
        total_backups_size = sum(b.file_size for b in BackupRecord.objects.all())

        context = {
            'config': config,
            'backups': backups,
            'total_backups_count': total_backups_count,
            'total_backups_size': total_backups_size,
            'selected_tier': tier_filter or '',
        }
        return render(request, 'admin/backups.html', context)

    def post(self, request):
        config = BackupConfiguration.get_config()
        config.is_enabled = request.POST.get('is_enabled') == 'on'
        config.backup_time = request.POST.get('backup_time', '02:00').strip()
        config.weekly_day = int(request.POST.get('weekly_day', 6))
        config.monthly_day = int(request.POST.get('monthly_day', 1))

        config.keep_daily = int(request.POST.get('keep_daily', 7))
        config.keep_weekly = int(request.POST.get('keep_weekly', 4))
        config.keep_monthly = int(request.POST.get('keep_monthly', 3))
        config.preserve_config_on_restore = request.POST.get('preserve_config_on_restore') == 'on'

        config.storage_type = request.POST.get('storage_type', 'LOCAL')
        config.local_path = request.POST.get('local_path', 'backups').strip()

        config.s3_endpoint_url = request.POST.get('s3_endpoint_url', '').strip() or None
        config.s3_bucket = request.POST.get('s3_bucket', '').strip()
        config.s3_region = request.POST.get('s3_region', 'us-east-1').strip()
        config.s3_access_key = request.POST.get('s3_access_key', '').strip()
        s3_sec = request.POST.get('s3_secret_key', '').strip()
        if s3_sec:
            config.s3_secret_key = s3_sec
        config.s3_prefix = request.POST.get('s3_prefix', 'sportsball/').strip()

        config.cifs_server = request.POST.get('cifs_server', '').strip()
        config.cifs_share = request.POST.get('cifs_share', '').strip()
        config.cifs_subpath = request.POST.get('cifs_subpath', '').strip()
        config.cifs_username = request.POST.get('cifs_username', '').strip()
        cifs_pwd = request.POST.get('cifs_password', '').strip()
        if cifs_pwd:
            config.cifs_password = cifs_pwd
        config.cifs_domain = request.POST.get('cifs_domain', '').strip()

        config.nfs_server = request.POST.get('nfs_server', '').strip()
        config.nfs_export = request.POST.get('nfs_export', '').strip()
        config.nfs_subpath = request.POST.get('nfs_subpath', '').strip()

        enc_pass = request.POST.get('encryption_passphrase', '').strip()
        if enc_pass:
            config.encryption_passphrase = enc_pass
        elif 'clear_encryption' in request.POST:
            config.encryption_passphrase = ''

        config.webhook_url = request.POST.get('webhook_url', '').strip()
        config.save()
        messages.success(request, "Backup configuration saved successfully.")
        return redirect('system_admin_backups')


class BackupManualTriggerView(SuperuserRequiredMixin, View):
    """Executes an immediate manual backup snapshot."""

    def post(self, request):
        config = BackupConfiguration.get_config()
        try:
            rec = execute_backup(tier='MANUAL', config=config)
            messages.success(request, f"Manual backup created successfully: {rec.filename} ({round(rec.file_size / 1024, 1)} KB)")
        except Exception as e:
            messages.error(request, f"Backup creation failed: {e}")
        return redirect('system_admin_backups')


class BackupTestConnectionApiView(SuperuserRequiredMixin, View):
    """Tests connectivity to the active or requested backup storage target."""

    def post(self, request):
        config = BackupConfiguration.get_config()
        storage_type = request.POST.get('storage_type', config.storage_type)
        
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


class DownloadBackupView(SuperuserRequiredMixin, View):
    """Streams backup snapshot archive to the administrator's browser."""

    def get(self, request, backup_uuid):
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


class RestoreBackupView(SuperuserRequiredMixin, View):
    """Executes database restoration from an existing BackupRecord."""

    def post(self, request, backup_uuid):
        rec = get_object_or_404(BackupRecord, uuid=backup_uuid)
        passphrase = request.POST.get('passphrase', '').strip()

        try:
            restore_backup(rec, passphrase=passphrase)
            messages.success(request, f"Platform database successfully restored from snapshot '{rec.filename}'.")
        except Exception as e:
            messages.error(request, f"Database restoration failed: {e}")

        return redirect('system_admin_backups')


class DeleteBackupView(SuperuserRequiredMixin, View):
    """Deletes backup file from storage and removes its catalog record."""

    def post(self, request, backup_uuid):
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


class SystemAdminUsersView(SuperuserRequiredMixin, View):
    """User roster, account search, activation status, and password resets."""

    def get(self, request):
        query = request.GET.get('q', '').strip()
        role_filter = request.GET.get('role', '').strip()
        users_qs = User.objects.all().order_by('-date_joined')

        if query:
            users_qs = users_qs.filter(
                Q(username__icontains=query) |
                Q(email__icontains=query) |
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query)
            )
        if role_filter:
            users_qs = users_qs.filter(role=role_filter)

        paginator = Paginator(users_qs, 30)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'page_obj': page_obj,
            'query': query,
            'role_filter': role_filter,
            'roles': User.ROLE_CHOICES,
            'total_count': paginator.count,
        }
        return render(request, 'admin/users.html', context)


class AdminResetUserPasswordView(SuperuserRequiredMixin, View):
    """Generates a temporary secure password for user."""

    def post(self, request, user_id: int):
        target_user = get_object_or_404(User, id=user_id)
        chars = string.ascii_letters + string.digits + '!@#$%'
        new_pwd = ''.join(secrets.choice(chars) for _ in range(12))
        target_user.set_password(new_pwd)
        target_user.save()
        messages.success(
            request,
            f"Password reset for {target_user.username}. Temporary password: {new_pwd}"
        )
        return redirect('system_admin_users')


class AdminToggleUserActiveView(SuperuserRequiredMixin, View):
    """Enables or disables a user account."""

    def post(self, request, user_id: int):
        target_user = get_object_or_404(User, id=user_id)
        if target_user == request.user:
            messages.error(request, "You cannot deactivate your own administrative account.")
            return redirect('system_admin_users')

        target_user.is_active = not target_user.is_active
        target_user.save(update_fields=['is_active'])
        status_str = "activated" if target_user.is_active else "deactivated"
        messages.success(request, f"Account {target_user.username} has been {status_str}.")
        return redirect('system_admin_users')


class AdminToggleMaintenanceModeView(SuperuserRequiredMixin, View):
    """Toggles global maintenance mode."""

    def post(self, request):
        setting = SystemSetting.get_settings()
        setting.maintenance_mode = not setting.maintenance_mode
        setting.save(update_fields=['maintenance_mode'])
        state_str = "ENABLED" if setting.maintenance_mode else "DISABLED"
        messages.success(request, f"Maintenance mode is now {state_str}.")
        return redirect('system_admin_dashboard')


class AdminUpdateEmergencyBannerView(SuperuserRequiredMixin, View):
    """Updates top alert banner text and active status."""

    def post(self, request):
        setting = SystemSetting.get_settings()
        setting.banner_active = request.POST.get('banner_active') == 'on'
        setting.banner_message = request.POST.get('banner_message', '').strip()
        setting.banner_link = request.POST.get('banner_link', '').strip()
        setting.save(update_fields=['banner_active', 'banner_message', 'banner_link'])
        messages.success(request, "Emergency alert banner updated.")
        return redirect('system_admin_dashboard')
