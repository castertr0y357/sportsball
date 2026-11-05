from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/waiver/', views.sign_waiver, name='sign_waiver'),
    path('players/<int:user_id>/', views.player_detail, name='player_detail'),
    path('free-agents/', views.free_agent_list, name='free_agent_list'),
]
