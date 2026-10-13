import logging

from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from shop.forms import (
    CarForm,
    CarImportForm,
    CarPartForm,
    FleetForm,
    GarageCreateForm,
    GarageInviteForm,
    GarageMembershipRoleForm,
    KnownShopForm,
    KnownShopProofForm,
    ReportForm,
    WorkJobForm,
)
from shop.importers import ImportContext
from shop.middleware import hanko_login_required
from shop.models.car import CarPart
from shop.models.garage import Garage, GarageInvitation, GarageMembership, KnownShop, KnownShopProof
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.permissions import GarageSharingPermissions, get_membership_or_404
from shop.services import update_car_odometer_from_report
from shop.services.attachments import save_attachments
from shop.view_helpers import (
    user_can_manage_garage,
    user_can_manage_known_shop,
    user_cars_queryset,
    user_garages_queryset,
    user_known_shops_queryset,
)
from shop.views.helpers import handle_model_form, process_import_form

security_log = logging.getLogger('security')

@hanko_login_required
def car_import(request: HttpRequest, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not user_can_manage_garage(request.user, car.garage):
        messages.error(request, _('You do not have permission to import data into this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))

    if request.method == 'POST':
        form = CarImportForm(request.POST, request.FILES)
        if form.is_valid():
            redirect_response = process_import_form(
                request,
                form,
                lambda: form.cleaned_data['import_type'],
                ImportContext(garage=car.garage, car=car, user=request.user),
                success_url=reverse('shop-car-detail', args=[car.pk]),
                success_message=lambda result: _('Imported %(count)s records for %(car)s.') % {
                    'count': result.created_count,
                    'car': car.usual_name or car.make,
                },
                dry_run_message=lambda result: _('Dry run complete for %(model)s: %(count)s records validated.') % {
                    'model': result.model_label,
                    'count': result.created_count,
                },
            )
            if redirect_response is not None:
                return redirect_response
    else:
        initial_import_type = request.GET.get('type')
        if initial_import_type not in {'workjob', 'report'}:
            initial_import_type = None
        form = CarImportForm(initial={'import_type': initial_import_type} if initial_import_type else None)

    return render(
        request,
        'shop/car_import.html',
        {
            'form': form,
            'car': car,
            'title': _('Import records for %(name)s') % {'name': car.usual_name or car.make},
            'subtitle': _('Upload normalized CSV for work jobs or reports tied to this car'),
        },
    )


@hanko_login_required
def car_list(request: HttpRequest) -> HttpResponse:
    """Display list of cars with basic info."""
    cars = user_cars_queryset(request.user).order_by('-created_at')
    manageable_garage_ids = set(
        GarageMembership.objects.filter(
            user=request.user,
            role__in=GarageMembership.WRITE_DATA_ROLES,
        ).values_list('garage_id', flat=True)
    )
    return render(
        request,
        'shop/car_list.html',
        {
            'cars': cars,
            'can_edit_garage_data': bool(manageable_garage_ids),
            'manageable_garage_ids': manageable_garage_ids,
        },
    )


@hanko_login_required
@require_POST
def car_delete(request: HttpRequest, pk: str) -> HttpResponse:
    """Delete a car from a garage the user can manage."""
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not user_can_manage_garage(request.user, car.garage):
        security_log.warning(
            'access_denied: user=%s path=%s reason=car_delete_not_manager car=%s garage=%s',
            request.user.pk,
            request.path,
            car.pk,
            car.garage_id,
        )
        messages.error(request, _('You do not have permission to delete this car.'))
        return redirect(reverse('shop-car-list'))

    car.delete()
    messages.success(request, _('Car deleted successfully.'))
    return redirect(reverse('shop-car-list'))


@hanko_login_required
def car_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show a single car's full details, maintenance plan and status ledger."""
    car = get_object_or_404(
        user_cars_queryset(request.user).select_related('garage').prefetch_related('work_jobs', 'reports', 'parts__status_history'),
        pk=pk,
    )
    show_done = request.GET.get('show_done') == '1'
    work_jobs_qs = car.work_jobs.order_by('status', 'planned_date', 'created_at')
    if not show_done:
        work_jobs_qs = work_jobs_qs.exclude(status__in=(WorkJob.STATUS_DONE, WorkJob.STATUS_CANCELLED))
    reports = car.reports.order_by('-date_done', '-created_at')
    parts = list(car.parts.order_by('name'))
    related_cars = (
        user_cars_queryset(request.user).filter(make=car.make, model=car.model)
        .exclude(pk=car.pk)
        .order_by('year', 'usual_name')
    )
    can_edit = GarageSharingPermissions(request.user, car.garage).can_edit_garage_data
    return render(
        request,
        'shop/car_detail.html',
        {
            'car': car,
            'related_cars': related_cars,
            'work_jobs': work_jobs_qs,
            'reports': reports,
            'parts': parts,
            'can_edit_garage_data': can_edit,
            'show_done': show_done,
        },
    )


@hanko_login_required
def car_create(request: HttpRequest) -> HttpResponse:
    """Create a new Car. Handles validation and shows errors in form."""
    if request.method == 'POST':
        form = CarForm(request.POST, user=request.user)
        if form.is_valid():
            garage = form.cleaned_data.get('garage')
            if garage is not None and not GarageSharingPermissions(request.user, garage).can_edit_garage_data:
                messages.error(request, _('You do not have permission to add a car to this fleet.'))
                return redirect(reverse('shop-car-list'))
            car = form.save()
            messages.success(request, _('Car created successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarForm(user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': True})


@hanko_login_required
def car_update(request: HttpRequest, pk: str) -> HttpResponse:
    """Update an existing Car. Preserves CSRF protection via template token."""
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to edit this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = CarForm(request.POST, instance=car, user=request.user)
        if form.is_valid():
            garage = form.cleaned_data.get('garage')
            if garage is not None and garage.pk != car.garage_id:
                if not GarageSharingPermissions(request.user, garage).can_edit_garage_data:
                    messages.error(request, _('You do not have permission to move this car to the selected fleet.'))
                    return redirect(reverse('shop-car-detail', args=[car.pk]))
            form.save()
            messages.success(request, _('Car updated successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarForm(instance=car, user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': False, 'car': car})


@hanko_login_required
def part_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add parts to this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))

    def _set_car(part: CarPart, _form) -> None:
        part.car = car

    return handle_model_form(
        request,
        CarPartForm,
        'shop/part_form.html',
        reverse('shop-car-detail', args=[car.pk]),
        save_callback=_set_car,
        success_message=_('Part status added successfully.'),
        context={'car': car},
    )


@hanko_login_required
def part_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update parts for this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    part = get_object_or_404(CarPart, pk=pk, car=car)
    return handle_model_form(
        request,
        CarPartForm,
        'shop/part_form.html',
        reverse('shop-car-detail', args=[car.pk]),
        instance=part,
        success_message=_('Part status updated successfully.'),
        context={'car': car, 'part': part},
    )


@hanko_login_required
def workjob_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add planned work to this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = WorkJobForm(request.POST, user=request.user, garage=car.garage)
        if form.is_valid():
            work_job = form.save(commit=False)
            work_job.car = car
            work_job.save()
            messages.success(request, _('Planned work added successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = WorkJobForm(user=request.user, garage=car.garage)
    return render(request, 'shop/workjob_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def workjob_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update planned work for this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    work_job = get_object_or_404(WorkJob, pk=pk, car=car)
    if request.method == 'POST':
        form = WorkJobForm(request.POST, instance=work_job, user=request.user, garage=car.garage)
        if form.is_valid():
            form.save()
            messages.success(request, _('Planned work updated successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = WorkJobForm(instance=work_job, user=request.user, garage=car.garage)
    return render(request, 'shop/workjob_form.html', {'form': form, 'is_create': False, 'car': car, 'work_job': work_job})


@hanko_login_required
def report_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add reports to this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = ReportForm(request.POST, request.FILES, user=request.user, garage=car.garage, car=car)
        if form.is_valid():
            with transaction.atomic():
                report = form.save(commit=False)
                report.car = car
                report.save()
                odometer_updated = update_car_odometer_from_report(report)
                save_attachments(
                    report,
                    form.cleaned_data.get('attachments', []),
                    form.cleaned_data.get('external_links', []),
                    staged=form.cleaned_data.get('staged_attachments'),
                )
            if odometer_updated:
                messages.info(
                    request,
                    _('Vehicle odometer updated to %(mileage)s km.') % {'mileage': report.mileage},
                )
            messages.success(request, _('Maintenance report added successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm(user=request.user, garage=car.garage, car=car)
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def report_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update reports for this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    report = get_object_or_404(Report, pk=pk, car=car)
    if request.method == 'POST':
        form = ReportForm(request.POST, request.FILES, instance=report, user=request.user, garage=car.garage, car=car)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                odometer_updated = update_car_odometer_from_report(report)
                save_attachments(
                    report,
                    form.cleaned_data.get('attachments', []),
                    form.cleaned_data.get('external_links', []),
                    staged=form.cleaned_data.get('staged_attachments'),
                )
            if odometer_updated:
                messages.info(
                    request,
                    _('Vehicle odometer updated to %(mileage)s km.') % {'mileage': report.mileage},
                )
            messages.success(request, _('Maintenance report updated successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm(instance=report, user=request.user, garage=car.garage, car=car)
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': False, 'car': car, 'report': report})


