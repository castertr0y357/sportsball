from django import forms
from .models import Church, Announcement


class ChurchForm(forms.ModelForm):
    class Meta:
        model = Church
        fields = [
            'name', 'denomination', 'address', 'city', 'state',
            'pastor_or_contact', 'contact_email', 'contact_phone',
            'website', 'description', 'commissioner', 'dues_paid',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = [
            'title', 'category', 'content', 'scripture_reference',
            'league', 'season', 'is_urgent',
        ]
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4}),
        }
