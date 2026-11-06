from django.contrib import admin
from .models import Church, Announcement


@admin.register(Church)
class ChurchAdmin(admin.ModelAdmin):
    list_display = ('name', 'denomination', 'city', 'state', 'commissioner', 'dues_paid', 'contact_email')
    search_fields = ('name', 'denomination', 'city', 'pastor_or_contact')
    list_filter = ('state', 'denomination', 'dues_paid')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'league', 'season', 'is_urgent', 'created_at')
    list_filter = ('category', 'is_urgent', 'league')
    search_fields = ('title', 'content', 'scripture_reference')
