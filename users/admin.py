from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name', 'role',
        'church', 'jersey_number', 'waiver_signed', 'is_expelled', 'is_free_agent'
    )
    list_filter = ('role', 'church', 'waiver_signed', 'is_expelled', 'is_free_agent', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'church__name', 'walkup_song_title')
    fieldsets = UserAdmin.fieldsets + (
        ('League Profile & Church Info', {
            'fields': (
                'role', 'church', 'phone', 'emergency_contact_name',
                'emergency_contact_phone', 'jersey_number', 'bio',
                'is_free_agent', 'waiver_signed', 'waiver_signed_at', 'waiver_signature'
            )
        }),
        ('Minor & Parental Safeguards', {
            'fields': (
                'birthdate', 'parent_guardian', 'parent_guardian_name',
                'parent_guardian_phone', 'parent_signed_waiver',
                'parent_waiver_signed_at', 'parent_waiver_signature'
            )
        }),
        ('Disciplinary & Expulsion Status', {
            'fields': (
                'is_expelled', 'expulsion_reason'
            )
        }),
        ('Ballpark Walk-Up Song', {
            'fields': (
                'walkup_song_title', 'walkup_song_file',
                'walkup_start_seconds', 'walkup_duration_seconds',
            )
        }),
    )
