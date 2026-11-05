from django.contrib import admin
from .models import Church, Announcement


@admin.register(Church)
class ChurchAdmin(admin.ModelAdmin):
    list_display = ('name', 'denomination', 'city', 'state', 'pastor_or_contact', 'contact_email')
    search_fields = ('name', 'denomination', 'city', 'pastor_or_contact')
    list_filter = ('state', 'denomination')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'league', 'season', 'is_pinned', 'is_urgent', 'created_at')
    list_filter = ('category', 'is_pinned', 'is_urgent', 'league')
    search_fields = ('title', 'content', 'scripture_reference')
