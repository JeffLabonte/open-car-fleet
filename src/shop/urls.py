from django.urls import path

from shop import views

urlpatterns = [
    path('login', views.login_view),
    path('login/', views.login_view, name='shop-login'),
    path('theme/<str:theme>/', views.theme_view, name='shop-theme'),
    path('logout/', views.logout_view, name='shop-logout'),
    path('auth/hanko/callback/', views.hanko_callback, name='shop-hanko-callback'),
    path('', views.index, name='shop-index'),
    path('garages/add/', views.garage_create, name='shop-garage-create'),
    path('garages/<uuid:pk>/', views.garage_detail, name='shop-garage-detail'),
    path('garages/<uuid:pk>/import/', views.garage_import, name='shop-garage-import'),
    path('garages/<uuid:pk>/share/', views.garage_share, name='shop-garage-share'),
    path('garages/invitations/accept/<uuid:token>/', views.garage_invitation_accept, name='shop-garage-invitation-accept'),
    path('cars/', views.car_list, name='shop-car-list'),
    path('cars/add/', views.car_create, name='shop-car-create'),
    path('cars/<uuid:pk>/', views.car_detail, name='shop-car-detail'),
    path('cars/<uuid:pk>/import/', views.car_import, name='shop-car-import'),
    path('cars/<uuid:pk>/edit/', views.car_update, name='shop-car-update'),
    path('cars/<uuid:car_pk>/work-jobs/add/', views.workjob_create, name='shop-workjob-create'),
    path('cars/<uuid:car_pk>/work-jobs/<int:pk>/edit/', views.workjob_update, name='shop-workjob-update'),
    path('cars/<uuid:car_pk>/reports/add/', views.report_create, name='shop-report-create'),
    path('cars/<uuid:car_pk>/reports/<int:pk>/edit/', views.report_update, name='shop-report-update'),
]
