from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count
from .models import CustomUser
from .forms import CustomUserCreationForm, ProfileForm, WaiverSignatureForm
from stats.models import PlayerGameStat


def register(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome to Church Sports Leagues, {user.display_name}!")
            return redirect('profile')
    else:
        form = CustomUserCreationForm()
    return render(request, 'users/register.html', {'form': form})


@login_required
def profile(request):
    user = request.user
    teams = user.teams.select_related('league', 'season', 'church').all()
    captained_teams = user.captained_teams.select_related('league', 'season', 'church').all()
    stat_totals = (
        PlayerGameStat.objects.filter(player=user)
        .values('category')
        .annotate(total=Sum('value'), games_count=Count('game', distinct=True))
        .order_by('-total')
    )
    recent_stats = (
        PlayerGameStat.objects.filter(player=user)
        .select_related('game__team1', 'game__team2', 'game__season')
        .order_by('-game__date')[:10]
    )
    return render(request, 'users/profile.html', {
        'profile_user': user,
        'teams': teams,
        'captained_teams': captained_teams,
        'stat_totals': stat_totals,
        'recent_stats': recent_stats,
    })


def player_detail(request, user_id):
    profile_user = get_object_or_404(CustomUser.objects.select_related('church'), id=user_id)
    teams = profile_user.teams.select_related('league', 'season', 'church').all()
    captained_teams = profile_user.captained_teams.select_related('league', 'season', 'church').all()
    stat_totals = (
        PlayerGameStat.objects.filter(player=profile_user)
        .values('category')
        .annotate(total=Sum('value'), games_count=Count('game', distinct=True))
        .order_by('-total')
    )
    recent_stats = (
        PlayerGameStat.objects.filter(player=profile_user)
        .select_related('game__team1', 'game__team2', 'game__season')
        .order_by('-game__date')[:10]
    )
    return render(request, 'users/profile.html', {
        'profile_user': profile_user,
        'teams': teams,
        'captained_teams': captained_teams,
        'stat_totals': stat_totals,
        'recent_stats': recent_stats,
    })


@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile and walk-up song settings have been updated.")
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'users/edit_profile.html', {'form': form})


@login_required
def sign_waiver(request):
    if request.method == 'POST':
        form = WaiverSignatureForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.sign_waiver(form.cleaned_data['signature'])
            messages.success(request, "Thank you! Your liability waiver and sportsmanship covenant have been certified.")
            return redirect('profile')
    else:
        initial_name = request.user.get_full_name() or request.user.username
        form = WaiverSignatureForm(user=request.user, initial={'signature': initial_name})
    return render(request, 'users/sign_waiver.html', {'form': form})


def free_agent_list(request):
    free_agents = CustomUser.objects.filter(is_free_agent=True).select_related('church').order_by('username')
    return render(request, 'users/free_agents.html', {'free_agents': free_agents})
