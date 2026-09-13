from django.urls import path

from car_docs import views

urlpatterns = [
    path('', views.car_doc_list, name='shop-car-doc-list'),
    path('add/', views.car_doc_create, name='shop-car-doc-create'),
    path('<int:pk>/', views.car_doc_detail, name='shop-car-doc-detail'),
    path('<int:pk>/edit/', views.car_doc_update, name='shop-car-doc-update'),
    path('<int:pk>/delete/', views.car_doc_delete, name='shop-car-doc-delete'),
]
