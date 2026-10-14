import logging

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from shop.decorators import require_fleet_permission
from shop.exporters import export_fleet_to_excel
from shop.forms import (
    FleetForm,
    FleetImportForm,
    FleetInviteForm,
    FleetMembershipRoleForm,
)
from shop.importers import ImportContext
from shop.middleware import hanko_login_required
from shop.models.fleet import FleetInvitation, FleetMembership
from shop.permissions import FleetSharingPermissions
from shop.services.invitations import (
    expire_stale_pending_invitations,
    invite_to_fleet,
)
from shop.view_helpers import (
    set_selected_fleet,
    user_fleets_queryset,
)
from shop.views.helpers import process_import_form

security_log = logging.getLogger("security")


@hanko_login_required
def index(request: HttpRequest) -> HttpResponse:
    """Authenticated homepage showing only fleets the user belongs to."""
    fleets = user_fleets_queryset(request.user).prefetch_related("cars").order_by("name")
    manageable_fleet_ids = set(
        FleetMembership.objects.filter(
            user=request.user,
            role__in=[FleetMembership.ROLE_OWNER, FleetMembership.ROLE_MANAGER],
        ).values_list("fleet_id", flat=True)
    )
    return render(
        request,
        "shop/fleet_list.html",
        {
            "title": _("My Fleets"),
            "subtitle": _("Fleets you belong to"),
            "fleets": fleets,
            "manageable_fleet_ids": manageable_fleet_ids,
        },
    )


@hanko_login_required
def fleet_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show one fleet and its cars for a member."""
    fleet = get_object_or_404(user_fleets_queryset(request.user).prefetch_related("cars"), pk=pk)
    set_selected_fleet(request, fleet)
    perms = FleetSharingPermissions(request.user, fleet)
    cars = fleet.cars.order_by("-created_at")
    return render(
        request,
        "shop/fleet_detail.html",
        {
            "fleet": fleet,
            "form": FleetForm(instance=fleet) if perms.can_manage_members else None,
            "can_manage_fleet": perms.can_manage_members,
            "can_edit_fleet_data": perms.can_edit_fleet_data,
            "cars": cars,
            "title": fleet.name,
            "subtitle": _("Review the vehicles in this fleet and manage access."),
        },
    )


@hanko_login_required
def fleet_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = FleetForm(request.POST)
        if form.is_valid():
            fleet = form.save(commit=False)
            fleet.created_by = request.user
            fleet.save()
            FleetMembership.objects.create(
                fleet=fleet,
                user=request.user,
                role=FleetMembership.ROLE_OWNER,
            )
            messages.success(request, _("Fleet created successfully."))
            return redirect(reverse("shop-fleet-detail", args=[fleet.pk]))
    else:
        form = FleetForm()

    return render(
        request,
        "shop/fleet_form.html",
        {
            "form": form,
            "is_create": True,
            "title": _("Create Fleet"),
            "subtitle": _("Set up a new shared workspace for your vehicles"),
        },
    )


@hanko_login_required
def fleet_update(request: HttpRequest, pk: str) -> HttpResponse:
    """Update an existing fleet's name and description."""
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    perms = FleetSharingPermissions(request.user, fleet)
    if not perms.can_manage_members:
        messages.error(request, _("You do not have permission to edit this fleet."))
        return redirect(reverse("shop-fleet-detail", args=[fleet.pk]))

    if request.method == "POST":
        form = FleetForm(request.POST, instance=fleet)
        if form.is_valid():
            form.save()
            messages.success(request, _("Fleet updated successfully."))
            return redirect(reverse("shop-fleet-detail", args=[fleet.pk]))
    else:
        form = FleetForm(instance=fleet)

    return render(
        request,
        "shop/fleet_detail.html",
        {
            "fleet": fleet,
            "form": form,
            "can_manage_fleet": perms.can_manage_members,
            "can_edit_fleet_data": perms.can_edit_fleet_data,
            "cars": fleet.cars.order_by("-created_at"),
            "title": fleet.name,
            "subtitle": _("Review the vehicles in this fleet and manage access."),
        },
    )


@hanko_login_required
def fleet_share(request: HttpRequest, pk: str) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    perms = FleetSharingPermissions(request.user, fleet)
    if not perms.can_manage_members:
        messages.error(request, _("You do not have permission to share this fleet."))
        return redirect(reverse("shop-fleet-detail", args=[fleet.pk]))

    if request.method == "POST":
        form = FleetInviteForm(request.POST, allowed_roles=perms.can_invite_with_role)
        if form.is_valid():
            invited_email = form.cleaned_data["invited_email"]
            expires_in_days = form.cleaned_data["expires_in_days"]
            message = form.cleaned_data["message"]
            role = form.cleaned_data["role"]

            if fleet.members.filter(email__iexact=invited_email).exists():
                messages.info(request, _("%(email)s is already a member of this fleet.") % {"email": invited_email})
            else:
                result = invite_to_fleet(
                    request,
                    fleet,
                    invited_email=invited_email,
                    role=role,
                    message=message,
                    invited_by=request.user,
                    expires_in_days=expires_in_days,
                )
                if result.updated:
                    messages.info(request, _("Updated pending invitation for %(email)s.") % {"email": invited_email})
                if result.email_sent:
                    if result.created:
                        messages.success(request, _("Invitation sent to %(email)s.") % {"email": invited_email})
                else:
                    messages.warning(
                        request,
                        (
                            _("Invitation created for %(email)s, but the email could not be sent. ")
                            % {"email": invited_email}
                        )
                        + _("Share this link manually: %(url)s") % {"url": result.accept_url},
                    )

            return redirect(reverse("shop-fleet-share", args=[fleet.pk]))
    else:
        form = FleetInviteForm(allowed_roles=perms.can_invite_with_role)

    expire_stale_pending_invitations(fleet)
    pending_invitations = fleet.invitations.filter(
        status=FleetInvitation.STATUS_PENDING,
    ).order_by("-created_at")

    return render(
        request,
        "shop/fleet_share.html",
        {
            "fleet": fleet,
            "form": form,
            "pending_invitations": pending_invitations,
            "title": _("Share %(name)s") % {"name": fleet.name},
            "subtitle": _("Invite people to collaborate in this fleet"),
        },
    )


@hanko_login_required
def fleet_members(request: HttpRequest, pk: str) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    perms = FleetSharingPermissions(request.user, fleet)
    if not perms.can_manage_members:
        messages.error(request, _("You do not have permission to manage fleet members."))
        return redirect(reverse("shop-fleet-detail", args=[fleet.pk]))

    members = fleet.memberships.select_related("user").order_by("-role", "created_at")
    return render(
        request,
        "shop/fleet_members.html",
        {
            "fleet": fleet,
            "members": members,
            "can_manage_members": perms.can_manage_members,
            "can_change_roles": [
                (role, label) for role, label in FleetMembership.ROLE_CHOICES if role in perms.can_change_role_to
            ],
            "title": _("Members of %(name)s") % {"name": fleet.name},
            "subtitle": _("Manage access and roles"),
        },
    )


@hanko_login_required
@require_POST
def fleet_member_role(request: HttpRequest, pk: str, membership_pk: int) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    perms = FleetSharingPermissions(request.user, fleet)
    if not perms.can_manage_members:
        messages.error(request, _("You do not have permission to change member roles."))
        return redirect(reverse("shop-fleet-members", args=[fleet.pk]))

    membership = get_object_or_404(fleet.memberships, pk=membership_pk)
    if not perms.can_manage_member(membership.role):
        security_log.warning(
            "access_denied: user=%s path=%s reason=role_change_hierarchy_violation target_user=%s target_role=%s",
            request.user.pk,
            request.path,
            membership.user_id,
            membership.role,
        )
        messages.error(request, _("You do not have permission to change this member's role."))
        return redirect(reverse("shop-fleet-members", args=[fleet.pk]))

    form = FleetMembershipRoleForm(request.POST, allowed_roles=perms.can_change_role_to)
    if form.is_valid():
        new_role = form.cleaned_data["role"]
        if membership.role == FleetMembership.ROLE_OWNER and new_role != FleetMembership.ROLE_OWNER:
            owner_count = fleet.memberships.filter(role=FleetMembership.ROLE_OWNER).count()
            if owner_count <= 1:
                messages.error(request, _("Cannot remove the last owner of the fleet."))
                return redirect(reverse("shop-fleet-members", args=[fleet.pk]))
        old_role = membership.role
        membership.role = new_role
        membership.save(update_fields=["role", "updated_at"])
        security_log.info(
            "role_changed: user=%s fleet=%s target_user=%s old_role=%s new_role=%s",
            request.user.pk,
            fleet.pk,
            membership.user_id,
            old_role,
            new_role,
        )
        messages.success(request, _("Role updated successfully."))
    else:
        messages.error(request, _("Invalid role selected."))

    return redirect(reverse("shop-fleet-members", args=[fleet.pk]))


@hanko_login_required
@require_POST
def fleet_member_remove(request: HttpRequest, pk: str, membership_pk: int) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    perms = FleetSharingPermissions(request.user, fleet)
    if not perms.can_remove_members:
        messages.error(request, _("You do not have permission to remove members."))
        return redirect(reverse("shop-fleet-members", args=[fleet.pk]))

    membership = get_object_or_404(fleet.memberships, pk=membership_pk)
    if not perms.can_manage_member(membership.role):
        security_log.warning(
            "access_denied: user=%s path=%s reason=member_remove_hierarchy_violation target_user=%s target_role=%s",
            request.user.pk,
            request.path,
            membership.user_id,
            membership.role,
        )
        messages.error(request, _("You do not have permission to remove this member."))
        return redirect(reverse("shop-fleet-members", args=[fleet.pk]))

    if membership.role == FleetMembership.ROLE_OWNER:
        owner_count = fleet.memberships.filter(role=FleetMembership.ROLE_OWNER).count()
        if owner_count <= 1:
            messages.error(request, _("Cannot remove the last owner of the fleet."))
            return redirect(reverse("shop-fleet-members", args=[fleet.pk]))

    target_user_id = membership.user_id
    target_role = membership.role
    membership.delete()
    security_log.info(
        "member_removed: user=%s fleet=%s target_user=%s target_role=%s",
        request.user.pk,
        fleet.pk,
        target_user_id,
        target_role,
    )
    messages.success(request, _("Member removed successfully."))
    return redirect(reverse("shop-fleet-members", args=[fleet.pk]))


@hanko_login_required
@require_POST
@require_fleet_permission(
    "can_manage_members",
    message=_("You do not have permission to manage fleet invitations."),
)
def fleet_invitation_cancel(request: HttpRequest, pk: str, invitation_pk: str) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    invitation = get_object_or_404(fleet.invitations, pk=invitation_pk)
    if invitation.status != FleetInvitation.STATUS_PENDING:
        messages.info(request, _("This invitation is no longer active."))
        return redirect(reverse("shop-fleet-share", args=[fleet.pk]))

    invitation.status = FleetInvitation.STATUS_CANCELLED
    invitation.save(update_fields=["status", "updated_at"])
    messages.success(request, _("Invitation to %(email)s cancelled.") % {"email": invitation.invited_email})
    return redirect(reverse("shop-fleet-share", args=[fleet.pk]))


@hanko_login_required
@require_fleet_permission(
    "can_manage_members",
    message=_("You do not have permission to import data into this fleet."),
    log_reason="fleet_import_not_manager",
)
def fleet_import(request: HttpRequest, pk: str) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)

    if request.method == "POST":
        form = FleetImportForm(request.POST, request.FILES)
        if form.is_valid():
            redirect_response = process_import_form(
                request,
                form,
                lambda: "car",
                ImportContext(fleet=fleet, user=request.user),
                success_url=reverse("shop-fleet-detail", args=[fleet.pk]),
                success_message=lambda result: (
                    _("Imported %(count)s records into %(fleet)s.")
                    % {
                        "count": result.created_count,
                        "fleet": fleet.name,
                    }
                ),
                dry_run_message=lambda result: (
                    _("Dry run complete for %(model)s: %(count)s records validated.")
                    % {
                        "model": result.model_label,
                        "count": result.created_count,
                    }
                ),
            )
            if redirect_response is not None:
                return redirect_response
    else:
        form = FleetImportForm()

    return render(
        request,
        "shop/fleet_import.html",
        {
            "form": form,
            "fleet": fleet,
            "title": _("Import cars into %(name)s") % {"name": fleet.name},
            "subtitle": _("Upload normalized CSV for cars assigned to this fleet"),
        },
    )


@hanko_login_required
@require_fleet_permission(
    "can_manage_members",
    message=_("You do not have permission to export data from this fleet."),
    log_reason="fleet_export_not_manager",
)
def fleet_export(request: HttpRequest, pk: str) -> HttpResponse:
    fleet = get_object_or_404(user_fleets_queryset(request.user), pk=pk)
    workbook = export_fleet_to_excel(fleet)
    response = HttpResponse(
        workbook.content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{workbook.filename}"'
    return response
