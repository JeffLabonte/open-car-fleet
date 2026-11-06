from typing import Any

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from shop.forms import (
    InspectionCarSelectForm,
    InspectionFilterForm,
    InspectionForm,
    InspectionPointFormSet,
    create_inspection_points,
)
from shop.middleware import hanko_login_required
from shop.models.fleet import Fleet, FleetMembership
from shop.models.inspection import Inspection
from shop.permissions import FleetSharingPermissions
from shop.services.attachments import save_attachments
from shop.view_helpers import get_selected_fleet, set_selected_fleet, user_cars_queryset


def _get_user_car(request: HttpRequest, pk: str):
    return get_object_or_404(user_cars_queryset(request.user).select_related("fleet"), pk=pk)


@hanko_login_required
@require_POST
def inspection_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    """Create a new draft inspection with the full checklist and redirect to edit it."""
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        messages.error(request, _("You do not have permission to add inspections to this car."))
        return redirect(reverse("shop-car-detail", args=[car.pk]))

    with transaction.atomic():
        inspection = Inspection.objects.create(
            car=car,
            inspected_at=timezone.now(),
            created_by=request.user,
            is_draft=True,
        )
        create_inspection_points(inspection)

    return redirect(reverse("shop-inspection-update", args=[car.pk, inspection.pk]))


def _save_inspection_from_request(
    request: HttpRequest,
    inspection: Inspection,
    car,
    *,
    finalize: bool,
) -> tuple[InspectionForm, InspectionPointFormSet | None, bool]:
    """Save the inspection and formset from POST data.

    Returns (form, point_formset, success).
    """
    form = InspectionForm(request.POST, request.FILES, instance=inspection, user=request.user)
    is_structured = inspection.points.exists()
    point_formset = None
    if is_structured:
        point_formset = InspectionPointFormSet(request.POST, instance=inspection, prefix="points")

    if not form.is_valid() or (point_formset is not None and not point_formset.is_valid()):
        return form, point_formset, False

    with transaction.atomic():
        form.save()
        if finalize:
            inspection.is_draft = False
            inspection.save(update_fields=["is_draft"])
        if point_formset is not None:
            point_formset.save()
        save_attachments(
            inspection,
            form.cleaned_data.get("attachments", []),
            form.cleaned_data.get("external_links", []),
            staged=form.cleaned_data.get("staged_attachments"),
        )
    return form, point_formset, True


@hanko_login_required
def inspection_update(request: HttpRequest, car_pk: str, pk: int) -> HttpResponse:
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        messages.error(request, _("You do not have permission to edit inspections for this car."))
        return redirect(reverse("shop-car-detail", args=[car.pk]))
    inspection = get_object_or_404(Inspection, pk=pk, car=car)
    is_structured = inspection.points.exists()

    if request.method == "POST":
        action = request.POST.get("action", "finalize")
        finalize = action == "finalize"
        form, point_formset, success = _save_inspection_from_request(request, inspection, car, finalize=finalize)
        if success:
            if finalize:
                messages.success(request, _("Inspection finalized successfully."))
            else:
                messages.success(request, _("Draft saved successfully."))
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
@require_POST
def inspection_autosave(request: HttpRequest, car_pk: str, pk: int) -> HttpResponse:
    """Autosave a draft inspection via AJAX and return JSON status."""
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        return JsonResponse({"ok": False, "error": _("Permission denied.")}, status=403)

    inspection = get_object_or_404(Inspection, pk=pk, car=car, is_draft=True)
    form, point_formset, success = _save_inspection_from_request(request, inspection, car, finalize=False)

    if success:
        return JsonResponse({"ok": True, "saved_at": inspection.updated_at.isoformat()})

    errors = form.errors
    if point_formset is not None:
        errors["points"] = point_formset.errors
    return JsonResponse({"ok": False, "errors": errors}, status=400)


@hanko_login_required
@require_POST
def inspection_delete(request: HttpRequest, car_pk: str, pk: int) -> HttpResponse:
    """Delete a draft inspection. Finalized inspections cannot be deleted."""
    car = _get_user_car(request, car_pk)
    if not FleetSharingPermissions(request.user, car.fleet).can_edit_fleet_data:
        messages.error(request, _("You do not have permission to delete inspections for this car."))
        return redirect(reverse("shop-car-detail", args=[car.pk]))

    inspection = get_object_or_404(Inspection, pk=pk, car=car)
    if not inspection.is_draft:
        messages.error(request, _("Only draft inspections can be deleted."))
        return redirect(reverse("shop-inspection-history", args=[car.pk]))

    inspection.delete()
    messages.success(request, _("Draft inspection deleted."))
    return redirect(reverse("shop-car-detail", args=[car.pk]))


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
    return render(
        request,
        "shop/inspection_history.html",
        {
            "car": car,
            "inspections": inspections,
            "title": _("Inspection history"),
            "subtitle": _("All recorded inspections and the work discovered during them."),
        },
    )


def _user_can_create_inspections(user: Any) -> bool:
    return FleetMembership.objects.filter(
        user=user,
        role__in=FleetMembership.WRITE_DATA_ROLES,
    ).exists()


@hanko_login_required
def inspection_list(request: HttpRequest) -> HttpResponse:
    """Global, paginated list of inspections visible to the user."""
    base_qs = (
        Inspection.objects.filter(car__in=user_cars_queryset(request.user))
        .select_related("car", "car__fleet", "created_by")
        .prefetch_related("points")
        .order_by(*Inspection.LATEST_ORDERING)
    )

    filter_form = InspectionFilterForm(request.GET or None, user=request.user)
    filtered_qs = filter_form.filter_queryset(base_qs)

    paginator = Paginator(filtered_qs, 25)
    page_number = request.GET.get("page")
    inspections = paginator.get_page(page_number)

    query_params = request.GET.copy()
    query_params.pop("page", None)

    return render(
        request,
        "shop/inspection_list.html",
        {
            "inspections": inspections,
            "filter_form": filter_form,
            "can_create": _user_can_create_inspections(request.user),
            "query_params": query_params,
            "title": _("Inspections"),
            "subtitle": _("Past inspections across your fleets."),
        },
    )


@hanko_login_required
def inspection_wizard(request: HttpRequest) -> HttpResponse:
    """Multi-step wizard: choose fleet, then choose car for a new inspection."""
    editable_fleets = Fleet.objects.filter(
        memberships__user=request.user,
        memberships__role__in=FleetMembership.WRITE_DATA_ROLES,
    ).distinct()

    if not editable_fleets.exists():
        messages.error(request, _("You do not have permission to add inspections to any fleet."))
        return redirect(reverse("shop-inspection-list"))

    initial: dict[str, Any] = {}
    fleet_pk = request.GET.get("fleet")
    if fleet_pk:
        if editable_fleets.filter(pk=fleet_pk).exists():
            initial["fleet"] = fleet_pk
    else:
        selected_fleet = get_selected_fleet(request)
        if selected_fleet and editable_fleets.filter(pk=selected_fleet.pk).exists():
            initial["fleet"] = selected_fleet.pk

    form = InspectionCarSelectForm(user=request.user, initial=initial)
    return render(
        request,
        "shop/inspection_wizard.html",
        {
            "form": form,
            "title": _("New inspection"),
            "subtitle": _("Select a fleet and vehicle to inspect."),
        },
    )


@hanko_login_required
@require_GET
def inspection_cars_for_fleet(request: HttpRequest) -> HttpResponse:
    """Return JSON of cars in the requested fleet for the wizard dropdown."""
    fleet_pk = request.GET.get("fleet")
    if not fleet_pk:
        return JsonResponse({"cars": []})

    editable_fleets = Fleet.objects.filter(
        memberships__user=request.user,
        memberships__role__in=FleetMembership.WRITE_DATA_ROLES,
    ).distinct()
    fleet = get_object_or_404(editable_fleets, pk=fleet_pk)

    cars = (
        user_cars_queryset(request.user)
        .filter(fleet=fleet)
        .order_by("usual_name", "make", "model")
        .values("pk", "usual_name", "make", "model", "year")
    )

    return JsonResponse(
        {
            "cars": [
                {
                    "pk": str(car["pk"]),
                    "name": "{} {} {} {}".format(
                        car["year"] or "",
                        car["make"] or "",
                        car["model"] or "",
                        f"({car['usual_name']})" if car["usual_name"] else "",
                    ).strip(),
                }
                for car in cars
            ]
        }
    )
