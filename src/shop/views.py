from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from .models.car import Car
from .models.job import WorkJob
from .models.report import Report
from .forms import CarCreateForm, CarUpdateForm, WorkJobForm, ReportForm


def login_view(request):
    return render(request, 'shop/login.html', {
        'title': 'Login',
        'subtitle': 'Authenticate with Hanko to continue',
        'hanko_api_url': request.environ.get('HANKO_API_URL', ''),
        'next_url': request.GET.get('next', '/'),
    })


@login_required
def index(request):
    """Simple homepage for the shop app."""
    return render(request, 'shop/index.html', {'title': 'Shop Home'})


@login_required
def car_list(request):
    """Display list of cars with basic info."""
    cars = Car.objects.order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars})


@login_required
def car_detail(request, pk):
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


@login_required
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


@login_required
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


@login_required
def workjob_create(request, car_pk):
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


@login_required
def workjob_update(request, car_pk, pk):
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


@login_required
def report_create(request, car_pk):
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


@login_required
def report_update(request, car_pk, pk):
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
