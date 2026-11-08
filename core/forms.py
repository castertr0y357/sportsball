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
            'league', 'season', 'is_urgent', 'is_banner', 'banner_active',
        ]
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not (user.is_overall_commissioner or user.is_league_admin):
            # Only League and Overall Commissioners can mark announcements urgent
            if 'is_urgent' in self.fields:
                self.fields['is_urgent'].widget = forms.HiddenInput()
                self.fields['is_urgent'].initial = False
                self.fields['is_urgent'].required = False
            if 'is_banner' in self.fields:
                self.fields['is_banner'].widget = forms.HiddenInput()
                self.fields['is_banner'].initial = False
                self.fields['is_banner'].required = False
            if 'banner_active' in self.fields:
                self.fields['banner_active'].widget = forms.HiddenInput()
                self.fields['banner_active'].initial = False
                self.fields['banner_active'].required = False
