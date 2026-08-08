import json
import os
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from shop.auth import complete_hanko_login
from shop.forms import (
    CarCreateForm,
    CarUpdateForm,
    GarageCreateForm,
    GarageInviteForm,
    ReportForm,
    WorkJobForm,
)
from shop.middleware import hanko_login_required
from shop.models.car import Car
from shop.models.garage import Garage, GarageInvitation, GarageMembership
from shop.models.job import WorkJob
from shop.models.report import Report


def _user_cars_queryset(request: HttpRequest):
    return Car.objects.filter(garage__members=request.user).distinct()


def _user_garages_queryset(request: HttpRequest):
    return Garage.objects.filter(members=request.user).distinct()


def _user_can_manage_garage(request: HttpRequest, garage: Garage) -> bool:
    return garage.memberships.filter(
        user=request.user,
        role__in=[GarageMembership.ROLE_OWNER, GarageMembership.ROLE_MANAGER],
    ).exists()


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
    })


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
    garages = _user_garages_queryset(request).prefetch_related('cars').order_by('name')
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
    garage = get_object_or_404(_user_garages_queryset(request).prefetch_related('cars'), pk=pk)
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
    garage = get_object_or_404(_user_garages_queryset(request), pk=pk)
    if not _user_can_manage_garage(request, garage):
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
    cars = _user_cars_queryset(request).order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars})


@hanko_login_required
def car_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show a single car's full details, maintenance plan and history."""
    car = get_object_or_404(
        _user_cars_queryset(request).prefetch_related('work_jobs', 'reports'),
        pk=pk,
    )
    work_jobs = car.work_jobs.order_by('status', 'planned_date', 'created_at')
    reports = car.reports.order_by('-date_done', '-created_at')
    related_cars = (
        _user_cars_queryset(request).filter(make=car.make, model=car.model)
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
    car = get_object_or_404(_user_cars_queryset(request), pk=pk)
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
    car = get_object_or_404(_user_cars_queryset(request), pk=car_pk)
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
    car = get_object_or_404(_user_cars_queryset(request), pk=car_pk)
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
    car = get_object_or_404(_user_cars_queryset(request), pk=car_pk)
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
    car = get_object_or_404(_user_cars_queryset(request), pk=car_pk)
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
