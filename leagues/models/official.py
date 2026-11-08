"""GameOfficialAssignment model tracking umpire/referee assignments, statuses, and stipends."""
from __future__ import annotations
from django.db import models
from django.conf import settings
from django.utils import timezone


class GameOfficialAssignment(models.Model):
    ROLE_CHOICES = [
        ('head_ref', 'Head Referee / Plate Umpire'),
        ('field_ref', 'Field Umpire / Line Judge'),
        ('scorekeeper', 'Official Scorekeeper'),
    ]
    STATUS_CHOICES = [
        ('assigned', 'Assigned (Pending Confirmation)'),
        ('confirmed', 'Confirmed In'),
        ('declined', 'Declined / Needs Sub'),
        ('completed', 'Officiated / Completed'),
    ]
    PAY_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('volunteer', 'Volunteer / Fellowship'),
    ]

    game = models.ForeignKey('Game', on_delete=models.CASCADE, related_name='official_assignments')
    official = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='officiating_assignments')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='head_ref')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='assigned')
    pay_amount = models.DecimalField(max_digits=6, decimal_places=2, default=30.00, help_text="Pay stipend for this assignment ($)")
    pay_status = models.CharField(max_length=20, choices=PAY_STATUS_CHOICES, default='unpaid')
    notes = models.CharField(max_length=150, blank=True, help_text="e.g. Needs sub due to work travel")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['game__date', 'role']
        unique_together = [('game', 'official', 'role')]

    def toggle_payment(self):
        """1-Tap toggle for referee fee disbursement."""
        if self.pay_status == 'paid':
            self.pay_status = 'unpaid'
            self.paid_at = None
        else:
            self.pay_status = 'paid'
            self.paid_at = timezone.now()
        self.save(update_fields=['pay_status', 'paid_at'])

    def __str__(self):
        return f"{self.official.display_name} - {self.get_role_display()} ({self.game})"


