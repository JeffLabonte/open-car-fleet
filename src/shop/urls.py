from django.urls import path

from . import views

urlpatterns = [
    path('login', views.login_view),
    path('login/', views.login_view, name='shop-login'),
    path('', views.index, name='shop-index'),
    path('cars/', views.car_list, name='shop-car-list'),
    path('cars/add/', views.car_create, name='shop-car-create'),
    path('cars/<uuid:pk>/', views.car_detail, name='shop-car-detail'),
    path('cars/<uuid:pk>/edit/', views.car_update, name='shop-car-update'),
    path('cars/<uuid:car_pk>/work-jobs/add/', views.workjob_create, name='shop-workjob-create'),
    path('cars/<uuid:car_pk>/work-jobs/<int:pk>/edit/', views.workjob_update, name='shop-workjob-update'),
    path('cars/<uuid:car_pk>/reports/add/', views.report_create, name='shop-report-create'),
    path('cars/<uuid:car_pk>/reports/<int:pk>/edit/', views.report_update, name='shop-report-update'),
]
