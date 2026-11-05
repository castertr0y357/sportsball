from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('churches/', views.church_list, name='church_list'),
    path('churches/create/', views.create_church, name='create_church'),
    path('churches/<int:church_id>/', views.church_detail, name='church_detail'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/create/', views.create_announcement, name='create_announcement'),
]
