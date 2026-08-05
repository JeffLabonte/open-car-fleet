from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='shop-index'),
    path('cars/', views.car_list, name='shop-car-list'),
    path('cars/add/', views.car_create, name='shop-car-create'),
    path('cars/<uuid:pk>/', views.car_detail, name='shop-car-detail'),
    path('cars/<uuid:pk>/edit/', views.car_update, name='shop-car-update'),
]
