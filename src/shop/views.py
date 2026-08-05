from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages

from .models.car import Car
from .forms import CarCreateForm, CarUpdateForm


def index(request):
    """Simple homepage for the shop app."""
    return render(request, 'shop/index.html', {'title': 'Shop Home'})


def car_list(request):
    """Display list of cars with basic info."""
    cars = Car.objects.order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars})


def car_detail(request, pk):
    """Show a single car's full details."""
    car = get_object_or_404(Car, pk=pk)
    return render(request, 'shop/car_detail.html', {'car': car})


def car_create(request):
    """Create a new Car. Handles validation and shows errors in form."""
    if request.method == 'POST':
        form = CarCreateForm(request.POST)
        if form.is_valid():
            car = form.save()
            messages.success(request, 'Car created successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarCreateForm()
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': True})


def car_update(request, pk):
    """Update an existing Car. Preserves CSRF protection via template token."""
    car = get_object_or_404(Car, pk=pk)
    if request.method == 'POST':
        form = CarUpdateForm(request.POST, instance=car)
        if form.is_valid():
            form.save()
            messages.success(request, 'Car updated successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarUpdateForm(instance=car)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': False, 'car': car})
