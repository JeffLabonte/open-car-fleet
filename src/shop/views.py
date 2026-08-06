import json
import os
from typing import Any, cast

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout
from django.views.decorators.csrf import csrf_exempt

from .auth import complete_hanko_login
from .middleware import hanko_login_required
from .models.car import Car
from .models.job import WorkJob
from .models.report import Report
from .forms import CarCreateForm, CarUpdateForm, WorkJobForm, ReportForm


@csrf_exempt
def login_view(request: HttpRequest) -> HttpResponse:
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
    request.session['hanko_authenticated'] = True
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
    """Simple homepage for the shop app."""
    return render(request, 'shop/index.html', {'title': 'Shop Home'})


@hanko_login_required
def car_list(request: HttpRequest) -> HttpResponse:
    """Display list of cars with basic info."""
    cars = Car.objects.order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars})


@hanko_login_required
def car_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show a single car's full details, maintenance plan and history."""
    car = get_object_or_404(
        Car.objects.prefetch_related('work_jobs', 'reports'),
        pk=pk,
    )
    work_jobs = car.work_jobs.order_by('status', 'planned_date', 'created_at')
    reports = car.reports.order_by('-date_done', '-created_at')
    related_cars = (
        Car.objects.filter(make=car.make, model=car.model)
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
        form = CarCreateForm(request.POST)
        if form.is_valid():
            car = form.save()
            messages.success(request, 'Car created successfully.')
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarCreateForm()
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': True})


@hanko_login_required
def car_update(request: HttpRequest, pk: str) -> HttpResponse:
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


@hanko_login_required
def workjob_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(Car, pk=car_pk)
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
    car = get_object_or_404(Car, pk=car_pk)
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
    car = get_object_or_404(Car, pk=car_pk)
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
    car = get_object_or_404(Car, pk=car_pk)
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
