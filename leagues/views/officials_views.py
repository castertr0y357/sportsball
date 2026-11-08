"""
Views for Officials, Referees & Umpires Hub, Assignment claims, and payment disbursements.
"""

from __future__ import annotations
from typing import Any
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import View
from leagues.models import Season, Game, GameOfficialAssignment
from leagues.views.mixins import SeasonAdminRequiredMixin
from users.models import CustomUser


class OfficialsHubView(SeasonAdminRequiredMixin, View):
    """Command Center for managing the officials pool, game assignments, and pay budget."""

    def get(self, request, season_id: int):
        season = self.get_season()
        budget_summary = season.get_officials_budget_summary()
        pool_members = season.officials_pool.all().order_by('first_name', 'last_name')
        pool_ids = set(pool_members.values_list('id', flat=True))

        candidate_officials = CustomUser.objects.filter(
            Q(role__in=['referee', 'coach', 'admin']) | Q(is_staff=True)
        ).exclude(id__in=pool_ids).order_by('first_name', 'last_name')[:25]

        games = season.games.select_related('team1', 'team2').prefetch_related('official_assignments__official').order_by('week_number', 'date', 'location')

        weeks_dict = {}
        for g in games:
            w = g.week_number or 1
            if w not in weeks_dict:
                weeks_dict[w] = []
            weeks_dict[w].append(g)
        weeks = sorted(weeks_dict.items(), key=lambda x: x[0])

        return render(request, 'leagues/officials_hub.html', {
            'season': season,
            'budget_summary': budget_summary,
            'pool_members': pool_members,
            'candidate_officials': candidate_officials,
            'weeks': weeks,
        })

    def post(self, request, season_id: int):
        season = self.get_season()
        action = request.POST.get('action')

        if action == 'update_budget':
            budget_val = request.POST.get('officials_budget', '0').strip()
            pay_val = request.POST.get('official_default_pay', '30').strip()
            try:
                season.officials_budget = float(budget_val)
                season.official_default_pay = float(pay_val)
                season.save(update_fields=['officials_budget', 'official_default_pay'])
                messages.success(request, "Updated officials season budget and default pay rate.")
            except ValueError:
                messages.error(request, "Invalid budget or pay amount.")

        elif action in ('add_to_pool', 'add_pool_member'):
            user_id = request.POST.get('user_id')
            user_to_add = get_object_or_404(CustomUser, id=user_id)
            season.officials_pool.add(user_to_add)
            messages.success(request, f"Added {user_to_add.display_name} to the season officials pool.")

        elif action in ('remove_from_pool', 'remove_pool_member'):
            user_id = request.POST.get('user_id')
            user_to_remove = get_object_or_404(CustomUser, id=user_id)
            season.officials_pool.remove(user_to_remove)
            messages.success(request, f"Removed {user_to_remove.display_name} from the officials pool.")

        elif action == 'assign_official':
            game_id = request.POST.get('game_id')
            official_id = request.POST.get('official_id')
            role = request.POST.get('role', 'head_ref')
            pay_val = request.POST.get('pay_amount') or season.official_default_pay

            game = get_object_or_404(Game, id=game_id, season=season)
            official = get_object_or_404(CustomUser, id=official_id)

            GameOfficialAssignment.objects.update_or_create(
                game=game,
                role=role,
                defaults={
                    'official': official,
                    'status': 'assigned',
                    'pay_amount': pay_val,
                    'pay_status': 'unpaid',
                }
            )
            season.officials_pool.add(official)
            messages.success(request, f"Assigned {official.display_name} as {role} for {game}.")

        elif action == 'remove_assignment':
            assignment_id = request.POST.get('assignment_id')
            GameOfficialAssignment.objects.filter(id=assignment_id, game__season=season).delete()
            messages.success(request, "Removed official assignment.")

        elif action == 'toggle_pay_status':
            assignment_id = request.POST.get('assignment_id')
            assignment = get_object_or_404(GameOfficialAssignment, id=assignment_id, game__season=season)
            assignment.toggle_payment()
            messages.success(request, f"Marked {assignment.official.display_name} as {assignment.get_pay_status_display()}.")

        return redirect('officials_hub', season_id=season.id)


class RespondOfficialAssignmentView(LoginRequiredMixin, View):
    """Official 1-tap confirmation or sub request ('Can't Make It')."""

    def post(self, request, assignment_id: int):
        return self._respond(request, assignment_id)

    def get(self, request, assignment_id: int):
        return self._respond(request, assignment_id)

    def _respond(self, request, assignment_id: int):
        assignment = get_object_or_404(
            GameOfficialAssignment.objects.select_related('game', 'official', 'game__season'),
            id=assignment_id
        )
        if not (request.user.id == assignment.official_id or request.user.can_manage_league(assignment.game.season.league)):
            messages.error(request, "You do not have permission to respond to this assignment.")
            return redirect('home')

        action = request.POST.get('action') or request.GET.get('action')
        if action == 'confirm':
            assignment.status = 'confirmed'
            assignment.notes = ''
            assignment.save(update_fields=['status', 'notes'])
            messages.success(request, f"✓ Confirmed! You are officiating {assignment.game.team1.name} vs {assignment.game.team2.name}.")
        elif action == 'request_sub':
            notes = request.POST.get('notes', 'Needs sub')
            assignment.status = 'declined'
            assignment.notes = notes
            assignment.save(update_fields=['status', 'notes'])
            messages.warning(request, f"⚠️ Sub requested. This assignment is now open for pool members to claim.")

        next_url = request.POST.get('next') or request.GET.get('next')
        return redirect(next_url or 'home')


class ClaimOfficialAssignmentView(LoginRequiredMixin, View):
    """Pool member 1-tap claim for games needing a substitute official."""

    def post(self, request, assignment_id: int):
        return self._claim(request, assignment_id)

    def get(self, request, assignment_id: int):
        return self._claim(request, assignment_id)

    def _claim(self, request, assignment_id: int):
        assignment = get_object_or_404(
            GameOfficialAssignment.objects.select_related('game', 'official', 'game__season'),
            id=assignment_id
        )
        season = assignment.game.season

        can_claim = (
            request.user in season.officials_pool.all() or
            request.user.role == 'referee' or
            request.user.can_manage_league(season.league)
        )
        if not can_claim:
            messages.error(request, "You must be in the approved officials pool to claim assignments.")
            return redirect('home')

        if assignment.status != 'declined':
            messages.info(request, "This assignment is already covered.")
            return redirect('home')

        old_official = assignment.official
        assignment.official = request.user
        assignment.status = 'confirmed'
        assignment.notes = f"Covered by {request.user.display_name} (subbed for {old_official.display_name})"
        assignment.save(update_fields=['official', 'status', 'notes'])
        season.officials_pool.add(request.user)

        messages.success(request, f"✋ You have claimed the assignment for {assignment.game}!")
        return redirect('home')


class ToggleOfficialPaymentView(LoginRequiredMixin, View):
    """1-Tap toggle for referee fee payment disbursement."""

    def post(self, request, assignment_id: int):
        assignment = get_object_or_404(
            GameOfficialAssignment.objects.select_related('game__season__league', 'official'),
            id=assignment_id
        )
        league = assignment.game.season.league if assignment.game.season else None
        if not (request.user.is_overall_commissioner or (league and request.user.can_manage_league(league))):
            messages.error(request, "Only league commissioners can manage official fee disbursements.")
            return redirect('officials_hub', season_id=assignment.game.season_id)

        assignment.toggle_payment()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'ok',
                'pay_status': assignment.pay_status,
                'is_paid': assignment.pay_status == 'paid',
                'pay_amount': float(assignment.pay_amount)
            })

        status_label = "Paid" if assignment.pay_status == 'paid' else "Unpaid"
        messages.success(request, f"Updated payment status for {assignment.official.display_name} ({assignment.get_role_display()}): {status_label}")
        return redirect('officials_hub', season_id=assignment.game.season_id)
