"""Church model representing member congregations, commissioners, and affiliation dues."""
from __future__ import annotations
import uuid
from django.db import models
from django.conf import settings
from django.urls import reverse


class Church(models.Model):
    name = models.CharField(max_length=150, unique=True)
    denomination = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    pastor_or_contact = models.CharField(max_length=120, blank=True, help_text="Primary pastor or sports ministry contact")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    commissioner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_churches',
        help_text="Church Commissioner / Sports Director who registers teams and designates captains"
    )
    dues_paid = models.BooleanField(
        default=False,
        help_text="Has the church paid annual/season league affiliation dues?"
    )
    invite_code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        null=True,
        help_text="Unique invite token for onboarding church pastor / sports commissioner"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import uuid
            self.invite_code = uuid.uuid4().hex[:10]
        super().save(*args, **kwargs)

    def get_invite_url(self, request=None):
        from django.urls import reverse
        rel = reverse('join_church_invite', args=[self.invite_code])
        return request.build_absolute_uri(rel) if request else rel

    class Meta:
        verbose_name_plural = "Churches"
        ordering = ['name']

    def __str__(self):
        return self.name

