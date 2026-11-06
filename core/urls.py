from django.urls import path
from . import views
from . import views_testing

urlpatterns = [
    path('', views.home, name='home'),
    path('my-church/', views.my_church, name='my_church'),
    path('churches/', views.church_list, name='church_list'),
    path('churches/create/', views.create_church, name='create_church'),
    path('churches/<int:church_id>/', views.church_detail, name='church_detail'),
    path('churches/<int:church_id>/assign-commissioner/', views.assign_church_commissioner, name='assign_church_commissioner'),
    path('churches/<int:church_id>/toggle-dues/', views.toggle_church_dues, name='toggle_church_dues'),
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/create/', views.create_announcement, name='create_announcement'),
    # In-App Sandbox & Test User Portal (Kubernetes & Browser Testing)
    path('testing-sandbox/', views_testing.test_users_portal, name='test_users_portal'),
    path('testing-sandbox/switch/<str:username>/', views_testing.quick_switch_test_user, name='quick_switch_test_user'),
    path('testing-sandbox/create/', views_testing.create_in_app_test_user, name='create_in_app_test_user'),
    path('testing-sandbox/reseed/', views_testing.reset_all_demo_data_in_app, name='reset_all_demo_data'),
]
