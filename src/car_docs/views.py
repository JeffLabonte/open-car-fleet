from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from car_docs.forms import CarDocForm
from car_docs.models import CarDoc
from shop.middleware import hanko_login_required
from shop.permissions import GarageSharingPermissions
from shop.view_helpers import save_attachments, user_car_docs_queryset, user_cars_queryset


@hanko_login_required
def car_doc_list(request, car_pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    docs = user_car_docs_queryset(request.user).filter(car=car)
    return render(request, 'car_docs/list.html', {
        'car': car,
        'docs': docs,
        'title': _('Documents for %(name)s') % {'name': car.usual_name or car.make},
        'subtitle': _('Vehicle notes and reference material'),
    })


@hanko_login_required
def car_doc_detail(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    doc = get_object_or_404(user_car_docs_queryset(request.user), pk=pk, car=car)
    return render(request, 'car_docs/detail.html', {
        'car': car,
        'doc': doc,
        'title': doc.title,
        'subtitle': _('Document details'),
    })


@hanko_login_required
def car_doc_create(request, car_pk):
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add documents to this car.'))
        return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    if request.method == 'POST':
        form = CarDocForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                doc = form.save(commit=False)
                doc.car = car
                doc.save()
                save_attachments(doc, form.cleaned_data.get('attachments', []), [])
            messages.success(request, _('Document added successfully.'))
            return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    else:
        form = CarDocForm()
    return render(request, 'car_docs/form.html', {
        'form': form,
        'car': car,
        'is_create': True,
        'title': _('Add document'),
        'subtitle': _('Add notes or supporting information'),
    })


@hanko_login_required
def car_doc_update(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update documents for this car.'))
        return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    doc = get_object_or_404(user_car_docs_queryset(request.user), pk=pk, car=car)
    if request.method == 'POST':
        form = CarDocForm(request.POST, request.FILES, instance=doc)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                save_attachments(doc, form.cleaned_data.get('attachments', []), [])
            messages.success(request, _('Document updated successfully.'))
            return redirect(reverse('shop-car-doc-detail', args=[car.pk, doc.pk]))
    else:
        form = CarDocForm(instance=doc)
    return render(request, 'car_docs/form.html', {
        'form': form,
        'car': car,
        'doc': doc,
        'is_create': False,
        'title': _('Edit document'),
        'subtitle': _('Update the vehicle note'),
    })


@hanko_login_required
def car_doc_delete(request, car_pk, pk):
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to delete documents from this car.'))
        return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    doc = get_object_or_404(CarDoc, pk=pk, car=car)
    if request.method == 'POST':
        doc.delete()
        messages.success(request, _('Document deleted successfully.'))
        return redirect(reverse('shop-car-doc-list', args=[car.pk]))
    return render(request, 'car_docs/confirm_delete.html', {
        'car': car,
        'doc': doc,
        'title': _('Delete %(title)s') % {'title': doc.title},
        'subtitle': _('Confirm document removal'),
    })
