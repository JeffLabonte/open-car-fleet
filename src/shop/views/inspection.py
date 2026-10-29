from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from shop.forms import (
    InspectionForm,
    InspectionPointFormSet,
    create_inspection_points,
)
from shop.middleware import hanko_login_required
from shop.models.inspection import Inspection
from shop.permissions import FleetSharingPermissions
from shop.services.attachments import save_attachments
from shop.view_helpers import set_selected_fleet, user_cars_queryset


def _get_user_car(request: HttpRequest, pk: str):
    return get_object_or_404(user_cars_queryset(request.user).select_related("fleet"), pk=pk)


@hanko_login_required
def inspection_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        messages.error(request, _("You do not have permission to add inspections to this car."))
        return redirect(reverse("shop-car-detail", args=[car.pk]))

    if request.method == "POST":
        form = InspectionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                inspection = form.save(commit=False)
                inspection.car = car
                inspection.created_by = request.user
                inspection.save()
                use_structured = form.cleaned_data.get("use_structured_checklist")
                if use_structured:
                    create_inspection_points(inspection)
                save_attachments(
                    inspection,
                    form.cleaned_data.get("attachments", []),
                    form.cleaned_data.get("external_links", []),
                    staged=form.cleaned_data.get("staged_attachments"),
                )
            messages.success(request, _("Inspection added successfully."))
            if use_structured:
                return redirect(reverse("shop-inspection-update", args=[car.pk, inspection.pk]))
            return redirect(reverse("shop-car-detail", args=[car.pk]))
    else:
        form = InspectionForm(user=request.user)

    return render(request, "shop/inspection_form.html", {"form": form, "is_create": True, "car": car})


@hanko_login_required
def inspection_update(request: HttpRequest, car_pk: str, pk: int) -> HttpResponse:
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        messages.error(request, _("You do not have permission to edit inspections for this car."))
        return redirect(reverse("shop-car-detail", args=[car.pk]))
    inspection = get_object_or_404(Inspection, pk=pk, car=car)
    is_structured = inspection.points.exists()

    if request.method == "POST":
        form = InspectionForm(request.POST, request.FILES, instance=inspection, user=request.user)
        point_formset = None
        if is_structured:
            point_formset = InspectionPointFormSet(request.POST, instance=inspection, prefix="points")
        if form.is_valid() and (point_formset is None or point_formset.is_valid()):
            with transaction.atomic():
                form.save()
                if point_formset is not None:
                    point_formset.save()
                save_attachments(
                    inspection,
                    form.cleaned_data.get("attachments", []),
                    form.cleaned_data.get("external_links", []),
                    staged=form.cleaned_data.get("staged_attachments"),
                )
            messages.success(request, _("Inspection updated successfully."))
            return redirect(reverse("shop-car-detail", args=[car.pk]))
    else:
        form = InspectionForm(instance=inspection, user=request.user)
        point_formset = None
        if is_structured:
            point_formset = InspectionPointFormSet(instance=inspection, prefix="points")

    return render(
        request,
        "shop/inspection_form.html",
        {
            "form": form,
            "is_create": False,
            "car": car,
            "inspection": inspection,
            "point_formset": point_formset,
            "is_structured": is_structured,
        },
    )


@hanko_login_required
def inspection_history(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = _get_user_car(request, car_pk)
    set_selected_fleet(request, car.fleet)
    inspections = (
        Inspection.objects.filter(car=car)
        .select_related("created_by")
        .prefetch_related(
            "attachments",
            "points",
            "recommended_work__assigned_to",
            "recommended_work__assigned_shop",
        )
        .order_by(*Inspection.LATEST_ORDERING)
    )
    can_edit = FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data
    return render(
        request,
        "shop/inspection_history.html",
        {
            "car": car,
            "inspections": inspections,
            "can_edit_fleet_data": can_edit,
            "title": _("Inspection history"),
            "subtitle": _("All recorded inspections and the work discovered during them."),
        },
    )
