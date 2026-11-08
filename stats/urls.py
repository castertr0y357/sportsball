from django.urls import path
from stats import views

urlpatterns = [
    path('', views.LeaderboardView.as_view(), name='leaderboard'),
]
