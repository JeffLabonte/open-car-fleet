import json
import os
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from shop.auth import complete_hanko_login
from shop.forms import (
    CarImportForm,
    CarCreateForm,
    CarUpdateForm,
    GarageCreateForm,
    GarageImportForm,
    GarageInviteForm,
    ReportForm,
    WorkJobForm,
)
from shop.importers import ImportContext, ImportValidationError, JSONImporter
from shop.middleware import hanko_login_required
from shop.models.garage import Garage, GarageInvitation, GarageMembership
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.view_helpers import user_can_manage_garage, user_cars_queryset, user_garages_queryset


def get_theme_from_request(request: HttpRequest) -> str:
    theme_cookie = request.COOKIES.get('theme')
    if theme_cookie in {'light', 'dark'}:
        return theme_cookie
    return 'light'


@csrf_exempt
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(reverse('shop-index'))

    return render(request, 'shop/login.html', {
        'title': 'Login',
        'subtitle': 'Authenticate with Hanko to continue',
        'hanko_api_url': os.environ.get('HANKO_API_URL', ''),
        'next_url': request.GET.get('next', '/'),
        'logged_out': request.GET.get('logged_out') == '1',
        'theme': get_theme_from_request(request),
    })


def theme_view(request: HttpRequest, theme: str) -> HttpResponse:
    if theme not in {'light', 'dark'}:
        theme = 'light'

    response = redirect(request.GET.get('next') or reverse('shop-index'))
    response.set_cookie('theme', theme, max_age=60 * 60 * 24 * 365, httponly=False, samesite='Lax')
    return response


@csrf_exempt
def hanko_callback(request: HttpRequest) -> JsonResponse:
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)

    raw_payload: Any
    try:
        raw_payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        raw_payload = {}

    payload: dict[str, Any] = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
    nested_user_data = payload.get('user')
    user_data: dict[str, Any] = cast(dict[str, Any], nested_user_data) if isinstance(nested_user_data, dict) else payload
    raw_session_token = payload.get('session_token')
    session_token = raw_session_token if isinstance(raw_session_token, str) else ''

    if not user_data:
        return JsonResponse({'ok': False, 'error': 'Missing user payload'}, status=400)

    user = complete_hanko_login(request, user_data)
    if session_token:
        request.session['hanko_session_token'] = session_token
    request.session['hanko_user_payload'] = user_data
    request.session.save()

    return JsonResponse({
        'ok': True,
        'user': {
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'display_name': user.display_name or user.username,
        },
    })


@hanko_login_required
def index(request: HttpRequest) -> HttpResponse:
    """Authenticated homepage showing only garages the user belongs to."""
    garages = user_garages_queryset(request.user).prefetch_related('cars').order_by('name')
    return render(
        request,
        'shop/garage_list.html',
        {
            'title': 'My Garages',
            'subtitle': 'Garages you belong to',
            'garages': garages,
        },
    )


@hanko_login_required
def garage_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show one garage and its cars for a member."""
    garage = get_object_or_404(user_garages_queryset(request.user).prefetch_related('cars'), pk=pk)
    cars = garage.cars.order_by('-created_at')
    return render(
        request,
        'shop/garage_detail.html',
        {
            'garage': garage,
            'cars': cars,
            'title': garage.name,
            'subtitle': 'Garage details',
        },
    )


@hanko_login_required
def garage_create(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = GarageCreateForm(request.POST)
        if form.is_valid():
            garage = form.save(commit=False)
            garage.created_by = request.user
            garage.save()
            GarageMembership.objects.create(
                garage=garage,
                user=request.user,
                role=GarageMembership.ROLE_OWNER,
            )
            messages.success(request, 'Garage created successfully.')
            return redirect(reverse('shop-garage-detail', args=[garage.pk]))
    else:
        form = GarageCreateForm()

    return render(
        request,
        'shop/garage_form.html',
        {
            'form': form,
            'is_create': True,
            'title': 'Create Garage',
            'subtitle': 'Set up a new shared workspace for your vehicles',
        },
    )


@hanko_login_required
def garage_share(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    if not user_can_manage_garage(request.user, garage):
        messages.error(request, 'You do not have permission to share this garage.')
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    if request.method == 'POST':
        form = GarageInviteForm(request.POST)
        if form.is_valid():
            invited_email = form.cleaned_data['invited_email']
            expires_in_days = form.cleaned_data['expires_in_days']
            message = form.cleaned_data['message']

            if garage.members.filter(email__iexact=invited_email).exists():
                messages.info(request, f'{invited_email} is already a member of this garage.')
            elif garage.invitations.filter(
                invited_email__iexact=invited_email,
                status=GarageInvitation.STATUS_PENDING,
            ).exists():
                messages.info(request, f'A pending invitation already exists for {invited_email}.')
            else:
                invitation = GarageInvitation.objects.create(
                    garage=garage,
                    invited_email=invited_email,
                    invited_by=request.user,
                    message=message,
                    expires_at=timezone.now() + timedelta(days=expires_in_days),
                )
                invitation_accept_url = request.build_absolute_uri(
                    reverse('shop-garage-invitation-accept', args=[invitation.token])
                )
                invitation_base_url = invitation_accept_url.rsplit('/', 2)[0]
                try:
                    invitation.send_invitation_email(
                        accept_base_url=invitation_base_url,
                        sender_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    )
                    messages.success(request, f'Invitation sent to {invited_email}.')
                except Exception:
                    messages.warning(
                        request,
                        (
                            f'Invitation created for {invited_email}, but the email could not be sent. '
                            f'Share this link manually: {invitation_accept_url}'
                        ),
                    )

            return redirect(reverse('shop-garage-share', args=[garage.pk]))
    else:
        form = GarageInviteForm()

    pending_invitations = garage.invitations.filter(
        status=GarageInvitation.STATUS_PENDING,
    ).order_by('-created_at')

    return render(
        request,
        'shop/garage_share.html',
        {
            'garage': garage,
            'form': form,
            'pending_invitations': pending_invitations,
            'title': f'Share {garage.name}',
            'subtitle': 'Invite people to collaborate in this garage',
        },
    )


@hanko_login_required
def garage_import(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    if not user_can_manage_garage(request.user, garage):
        messages.error(request, 'You do not have permission to import data into this garage.')
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    if request.method == 'POST':
        form = GarageImportForm(request.POST, request.FILES)
        if form.is_valid():
            importer = JSONImporter()
            uploaded_file = form.cleaned_data['import_file']
            dry_run = form.cleaned_data['dry_run']
            try:
                records = importer.parse_json_bytes(uploaded_file.read(), source_name=uploaded_file.name)
                result = importer.import_records(
                    importer.resolve_model('car'),
                    records,
                    context=ImportContext(garage=garage),
                    dry_run=dry_run,
                )
            except ImportValidationError as exc:
                form.add_error('import_file', str(exc))
            else:
                for warning in result.warnings:
                    messages.warning(request, f"Record {warning.record_number}: {warning.message}")

                if result.has_errors:
                    for error in result.errors:
                        messages.error(request, f"Record {error.record_number}: {error.message}")
                    form.add_error('import_file', 'Import validation failed. Fix the file and try again.')
                else:
                    if dry_run:
                        messages.success(
                            request,
                            f"Dry run complete for {result.model_label}: {result.created_count} records validated.",
                        )
                    else:
                        messages.success(
                            request,
                            f"Imported {result.created_count} records into {garage.name}.",
                        )
                        return redirect(reverse('shop-garage-detail', args=[garage.pk]))
    else:
        form = GarageImportForm()

    return render(
        request,
        'shop/garage_import.html',
        {
            'form': form,
            'garage': garage,
            'title': f'Import cars into {garage.name}',
            'subtitle': 'Upload normalized JSON for cars assigned to this garage',
        },
    )


@hanko_login_required
def car_import(request: HttpRequest, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not user_can_manage_garage(request.user, car.garage):
        messages.error(request, 'You do not have permission to import data into this car.')
        return redirect(reverse('shop-car-detail', args=[car.pk]))

    if request.method == 'POST':
        form = CarImportForm(request.POST, request.FILES)
        if form.is_valid():
            importer = JSONImporter()
            uploaded_file = form.cleaned_data['import_file']
            dry_run = form.cleaned_data['dry_run']
            try:
                model = importer.resolve_model(form.cleaned_data['import_type'])
                records = importer.parse_json_bytes(uploaded_file.read(), source_name=uploaded_file.name)
                result = importer.import_records(
                    model,
                    records,
                    context=ImportContext(garage=car.garage, car=car),
                    dry_run=dry_run,
                )
            except ImportValidationError as exc:
                form.add_error('import_file', str(exc))
            else:
                for warning in result.warnings:
                    messages.warning(request, f"Record {warning.record_number}: {warning.message}")

                if result.has_errors:
                    for error in result.errors:
                        messages.error(request, f"Record {error.record_number}: {error.message}")
                    form.add_error('import_file', 'Import validation failed. Fix the file and try again.')
                else:
                    if dry_run:
                        messages.success(
                            request,
                            f"Dry run complete for {result.model_label}: {result.created_count} records validated.",
                        )
                    else:
                        messages.success(
                            request,
                            f"Imported {result.created_count} records for {car.usual_name or car.make}.",
                        )
                        return redirect(reverse('shop-car-detail', args=[car.pk]))
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
            'title': f'Import records for {car.usual_name or car.make}',
            'subtitle': 'Upload normalized JSON for work jobs or reports tied to this car',
        },
    )


@hanko_login_required
def garage_invitation_accept(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        GarageInvitation.objects.select_related('garage'),
        token=token,
    )

    if invitation.status != GarageInvitation.STATUS_PENDING:
        messages.info(request, 'This invitation is no longer active.')
        return redirect(reverse('shop-index'))

    if invitation.is_expired:
        invitation.status = GarageInvitation.STATUS_EXPIRED
        invitation.save(update_fields=['status'])
        messages.error(request, 'This invitation has expired.')
        return redirect(reverse('shop-index'))

    user_email = (request.user.email or '').strip().lower()
    invited_email = invitation.invited_email.strip().lower()
    if not user_email or user_email != invited_email:
        messages.error(
            request,
            f"Sign in with {invitation.invited_email} to accept this invitation.",
        )
        return redirect(reverse('shop-index'))

    _, created = GarageMembership.objects.get_or_create(
        garage=invitation.garage,
        user=request.user,
        defaults={'role': GarageMembership.ROLE_MEMBER},
    )
    invitation.status = GarageInvitation.STATUS_ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = request.user
    invitation.save(update_fields=['status', 'accepted_at', 'accepted_by'])

    if created:
        messages.success(request, f"You have joined '{invitation.garage.name}'.")
    else:
        messages.info(request, f"You are already a member of '{invitation.garage.name}'.")
    return redirect(reverse('shop-garage-detail', args=[invitation.garage.pk]))


@hanko_login_required
def car_list(request: HttpRequest) -> HttpResponse:
    """Display list of cars with basic info."""
    cars = user_cars_queryset(request.user).order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars})


@hanko_login_required
def car_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show a single car's full details, maintenance plan and history."""
    car = get_object_or_404(
        user_cars_queryset(request.user).prefetch_related('work_jobs', 'reports'),
        pk=pk,
    )
    work_jobs = car.work_jobs.order_by('status', 'planned_date', 'created_at')
    reports = car.reports.order_by('-date_done', '-created_at')
    related_cars = (
        user_cars_queryset(request.user).filter(make=car.make, model=car.model)
        .exclude(pk=car.pk)
        .order_by('year', 'usual_name')
    )
    return render(
        request,
        'shop/car_detail.html',
        {
            'car': car,
            'related_cars': related_cars,
            'work_jobs': work_jobs,
            'reports': reports,
        },
    )


@hanko_login_required
def car_create(request: HttpRequest) -> HttpResponse:
    """Create a new Car. Handles validation and shows errors in form."""
    if request.method == 'POST':
        form = CarCreateForm(request.POST, user=request.user)
        if form.is_valid():
            car = form.save()
            messages.success(request, 'Car created successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarCreateForm(user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': True})


@hanko_login_required
def car_update(request: HttpRequest, pk: str) -> HttpResponse:
    """Update an existing Car. Preserves CSRF protection via template token."""
    car = get_object_or_404(user_cars_queryset(request.user), pk=pk)
    if request.method == 'POST':
        form = CarUpdateForm(request.POST, instance=car, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Car updated successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarUpdateForm(instance=car, user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': False, 'car': car})


@hanko_login_required
def workjob_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    if request.method == 'POST':
        form = WorkJobForm(request.POST)
        if form.is_valid():
            work_job = form.save(commit=False)
            work_job.car = car
            work_job.save()
            messages.success(request, 'Planned work added successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = WorkJobForm()
    return render(request, 'shop/workjob_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def workjob_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    work_job = get_object_or_404(WorkJob, pk=pk, car=car)
    if request.method == 'POST':
        form = WorkJobForm(request.POST, instance=work_job)
        if form.is_valid():
            form.save()
            messages.success(request, 'Planned work updated successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = WorkJobForm(instance=work_job)
    return render(request, 'shop/workjob_form.html', {'form': form, 'is_create': False, 'car': car, 'work_job': work_job})


@hanko_login_required
def report_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.car = car
            report.save()
            messages.success(request, 'Maintenance report added successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm()
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def report_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user), pk=car_pk)
    report = get_object_or_404(Report, pk=pk, car=car)
    if request.method == 'POST':
        form = ReportForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            messages.success(request, 'Maintenance report updated successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm(instance=report)
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': False, 'car': car, 'report': report})


def logout_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        logout(request)
        messages.success(request, 'Logged out successfully.')
    return redirect(f"{reverse('shop-login')}?logged_out=1")
