from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name', 'role',
        'church', 'jersey_number', 'walkup_song_title', 'waiver_signed', 'is_free_agent'
    )
    list_filter = ('role', 'church', 'waiver_signed', 'is_free_agent', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'church__name', 'walkup_song_title')
    fieldsets = UserAdmin.fieldsets + (
        ('League Profile & Church Info', {
            'fields': (
                'role', 'church', 'phone', 'emergency_contact_name',
                'emergency_contact_phone', 'jersey_number', 'bio',
                'is_free_agent', 'waiver_signed', 'waiver_signed_at', 'waiver_signature'
            )
        }),
        ('Ballpark Walk-Up Song', {
            'fields': (
                'walkup_song_title', 'walkup_song_file',
                'walkup_start_seconds', 'walkup_duration_seconds',
            )
        }),
    )
