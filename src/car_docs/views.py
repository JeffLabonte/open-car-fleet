from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from car_docs.forms import CarDocForm
from car_docs.models import CarDoc
from shop.middleware import hanko_login_required
from shop.view_helpers import user_cars_queryset


@hanko_login_required
def car_doc_list(request, car_pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    docs = CarDoc.objects.filter(car=car).order_by('-updated_at', '-created_at')
    return render(request, 'car_docs/list.html', {
        'car': car,
        'docs': docs,
        'title': f'Documents for {car.usual_name or car.make}',
        'subtitle': 'Vehicle notes and reference material',
    })


@hanko_login_required
def car_doc_detail(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    doc = get_object_or_404(CarDoc, pk=pk, car=car)
    return render(request, 'car_docs/detail.html', {
        'car': car,
        'doc': doc,
        'title': doc.title,
        'subtitle': 'Document details',
    })


@hanko_login_required
def car_doc_create(request, car_pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    if request.method == 'POST':
        form = CarDocForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.car = car
            doc.save()
            messages.success(request, 'Document added successfully.')
            return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    else:
        form = CarDocForm()
    return render(request, 'car_docs/form.html', {
        'form': form,
        'car': car,
        'is_create': True,
        'title': 'Add document',
        'subtitle': 'Add notes or supporting information',
    })


@hanko_login_required
def car_doc_update(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    doc = get_object_or_404(CarDoc, pk=pk, car=car)
    if request.method == 'POST':
        form = CarDocForm(request.POST, request.FILES, instance=doc)
        if form.is_valid():
            form.save()
            messages.success(request, 'Document updated successfully.')
            return redirect(reverse('shop-car-doc-detail', args=[car.pk, doc.pk]))
    else:
        form = CarDocForm(instance=doc)
    return render(request, 'car_docs/form.html', {
        'form': form,
        'car': car,
        'doc': doc,
        'is_create': False,
        'title': 'Edit document',
        'subtitle': 'Update the vehicle note',
    })


@hanko_login_required
def car_doc_delete(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    doc = get_object_or_404(CarDoc, pk=pk, car=car)
    if request.method == 'POST':
        doc.delete()
        messages.success(request, 'Document deleted successfully.')
        return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    return render(request, 'car_docs/confirm_delete.html', {
        'car': car,
        'doc': doc,
        'title': f'Delete {doc.title}',
        'subtitle': 'Confirm document removal',
    })
