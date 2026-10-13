from datetime import timedelta
import logging

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from shop.decorators import require_garage_permission
from shop.exporters import export_garage_to_excel
from shop.forms import (
    CarImportForm,
    CarCreateForm,
    CarPartForm,
    CarUpdateForm,
    FleetUpdateForm,
    GarageCreateForm,
    GarageImportForm,
    GarageInviteForm,
    GarageMembershipRoleForm,
    KnownShopForm,
    KnownShopProofForm,
    ReportForm,
    WorkJobForm,
)
from shop.importers import CSVImporter, ImportContext, ImportValidationError
from shop.middleware import hanko_login_required
from shop.models.garage import Garage, GarageInvitation, GarageMembership, KnownShop, KnownShopProof
from shop.permissions import GarageSharingPermissions, get_membership_or_404
from shop.view_helpers import (
    save_attachments,
    user_can_manage_garage,
    user_can_manage_known_shop,
    user_cars_queryset,
    user_garages_queryset,
    user_known_shops_queryset,
)

security_log = logging.getLogger('security')

@hanko_login_required
def index(request: HttpRequest) -> HttpResponse:
    """Authenticated homepage showing only garages the user belongs to."""
    garages = user_garages_queryset(request.user).prefetch_related('cars').order_by('name')
    manageable_garage_ids = set(
        GarageMembership.objects.filter(
            user=request.user,
            role__in=[GarageMembership.ROLE_OWNER, GarageMembership.ROLE_MANAGER],
        ).values_list('garage_id', flat=True)
    )
    return render(
        request,
        'shop/fleet_list.html',
        {
            'title': _('My Fleets'),
            'subtitle': _('Fleets you belong to'),
            'garages': garages,
            'manageable_garage_ids': manageable_garage_ids,
        },
    )


@hanko_login_required
def garage_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Show one garage and its cars for a member."""
    garage = get_object_or_404(user_garages_queryset(request.user).prefetch_related('cars'), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    cars = garage.cars.order_by('-created_at')
    return render(
        request,
        'shop/fleet_detail.html',
        {
            'garage': garage,
            'form': FleetUpdateForm(instance=garage) if perms.can_manage_members else None,
            'can_manage_garage': perms.can_manage_members,
            'can_edit_garage_data': perms.can_edit_garage_data,
            'cars': cars,
            'title': garage.name,
            'subtitle': _('Fleet details'),
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
            messages.success(request, _('Fleet created successfully.'))
            return redirect(reverse('shop-garage-detail', args=[garage.pk]))
    else:
        form = GarageCreateForm()

    return render(
        request,
        'shop/fleet_form.html',
        {
            'form': form,
            'is_create': True,
            'title': _('Create Fleet'),
            'subtitle': _('Set up a new shared workspace for your vehicles'),
        },
    )


@hanko_login_required
def garage_update(request: HttpRequest, pk: str) -> HttpResponse:
    """Update an existing garage's name and description."""
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    if not perms.can_manage_members:
        messages.error(request, _('You do not have permission to edit this fleet.'))
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    if request.method == 'POST':
        form = FleetUpdateForm(request.POST, instance=garage)
        if form.is_valid():
            form.save()
            messages.success(request, _('Fleet updated successfully.'))
            return redirect(reverse('shop-garage-detail', args=[garage.pk]))
    else:
        form = FleetUpdateForm(instance=garage)

    return render(
        request,
        'shop/fleet_detail.html',
        {
            'garage': garage,
            'form': form,
            'can_manage_garage': perms.can_manage_members,
            'can_edit_garage_data': perms.can_edit_garage_data,
            'cars': garage.cars.order_by('-created_at'),
            'title': garage.name,
            'subtitle': _('Fleet details'),
        },
    )


def _expire_stale_pending_invitations(garage: Garage) -> None:
    now = timezone.now()
    expired_ids = list(
        garage.invitations.filter(
            status=GarageInvitation.STATUS_PENDING,
            expires_at__lte=now,
        ).values_list('id', flat=True)
    )
    if expired_ids:
        GarageInvitation.objects.filter(id__in=expired_ids).update(
            status=GarageInvitation.STATUS_EXPIRED
        )


@hanko_login_required
def garage_share(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    if not perms.can_manage_members:
        messages.error(request, _('You do not have permission to share this fleet.'))
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    if request.method == 'POST':
        form = GarageInviteForm(request.POST, allowed_roles=perms.can_invite_with_role)
        if form.is_valid():
            invited_email = form.cleaned_data['invited_email']
            expires_in_days = form.cleaned_data['expires_in_days']
            message = form.cleaned_data['message']
            role = form.cleaned_data['role']

            if garage.members.filter(email__iexact=invited_email).exists():
                messages.info(request, _('%(email)s is already a member of this fleet.') % {'email': invited_email})
            else:
                _expire_stale_pending_invitations(garage)
                existing_pending = garage.invitations.filter(
                    invited_email__iexact=invited_email,
                    status=GarageInvitation.STATUS_PENDING,
                ).first()
                if existing_pending:
                    existing_pending.role = role
                    existing_pending.expires_at = timezone.now() + timedelta(days=expires_in_days)
                    existing_pending.save(update_fields=['role', 'expires_at', 'updated_at'])
                    invitation = existing_pending
                    messages.info(request, _('Updated pending invitation for %(email)s.') % {'email': invited_email})
                else:
                    invitation = GarageInvitation.objects.create(
                        garage=garage,
                        invited_email=invited_email,
                        invited_by=request.user,
                        message=message,
                        role=role,
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
                    if not existing_pending:
                        messages.success(request, _('Invitation sent to %(email)s.') % {'email': invited_email})
                except Exception:
                    messages.warning(
                        request,
                        (
                            _('Invitation created for %(email)s, but the email could not be sent. ')
                            % {'email': invited_email}
                        )
                        + _('Share this link manually: %(url)s') % {'url': invitation_accept_url},
                    )

            return redirect(reverse('shop-garage-share', args=[garage.pk]))
    else:
        form = GarageInviteForm(allowed_roles=perms.can_invite_with_role)

    _expire_stale_pending_invitations(garage)
    pending_invitations = garage.invitations.filter(
        status=GarageInvitation.STATUS_PENDING,
    ).order_by('-created_at')

    return render(
        request,
        'shop/fleet_share.html',
        {
            'garage': garage,
            'form': form,
            'pending_invitations': pending_invitations,
            'title': _('Share %(name)s') % {'name': garage.name},
            'subtitle': _('Invite people to collaborate in this fleet'),
        },
    )


@hanko_login_required
def garage_members(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    if not perms.can_manage_members:
        messages.error(request, _('You do not have permission to manage fleet members.'))
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    members = garage.memberships.select_related('user').order_by(
        '-role', 'created_at'
    )
    return render(
        request,
        'shop/fleet_members.html',
        {
            'garage': garage,
            'members': members,
            'can_manage_members': perms.can_manage_members,
            'can_change_roles': [
                (role, label)
                for role, label in GarageMembership.ROLE_CHOICES
                if role in perms.can_change_role_to
            ],
            'title': _('Members of %(name)s') % {'name': garage.name},
            'subtitle': _('Manage access and roles'),
        },
    )


@hanko_login_required
@require_POST
def garage_member_role(request: HttpRequest, pk: str, membership_pk: int) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    if not perms.can_manage_members:
        messages.error(request, _('You do not have permission to change member roles.'))
        return redirect(reverse('shop-garage-members', args=[garage.pk]))

    membership = get_object_or_404(garage.memberships, pk=membership_pk)
    if not perms.can_manage_member(membership.role):
        security_log.warning(
            'access_denied: user=%s path=%s reason=role_change_hierarchy_violation target_user=%s target_role=%s',
            request.user.pk,
            request.path,
            membership.user_id,
            membership.role,
        )
        messages.error(request, _('You do not have permission to change this member\'s role.'))
        return redirect(reverse('shop-garage-members', args=[garage.pk]))

    form = GarageMembershipRoleForm(request.POST, allowed_roles=perms.can_change_role_to)
    if form.is_valid():
        new_role = form.cleaned_data['role']
        if membership.role == GarageMembership.ROLE_OWNER and new_role != GarageMembership.ROLE_OWNER:
            owner_count = garage.memberships.filter(role=GarageMembership.ROLE_OWNER).count()
            if owner_count <= 1:
                messages.error(request, _('Cannot remove the last owner of the fleet.'))
                return redirect(reverse('shop-garage-members', args=[garage.pk]))
        old_role = membership.role
        membership.role = new_role
        membership.save(update_fields=['role', 'updated_at'])
        security_log.info(
            'role_changed: user=%s garage=%s target_user=%s old_role=%s new_role=%s',
            request.user.pk,
            garage.pk,
            membership.user_id,
            old_role,
            new_role,
        )
        messages.success(request, _('Role updated successfully.'))
    else:
        messages.error(request, _('Invalid role selected.'))

    return redirect(reverse('shop-garage-members', args=[garage.pk]))


@hanko_login_required
@require_POST
def garage_member_remove(request: HttpRequest, pk: str, membership_pk: int) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    perms = GarageSharingPermissions(request.user, garage)
    if not perms.can_remove_members:
        messages.error(request, _('You do not have permission to remove members.'))
        return redirect(reverse('shop-garage-members', args=[garage.pk]))

    membership = get_object_or_404(garage.memberships, pk=membership_pk)
    if not perms.can_manage_member(membership.role):
        security_log.warning(
            'access_denied: user=%s path=%s reason=member_remove_hierarchy_violation target_user=%s target_role=%s',
            request.user.pk,
            request.path,
            membership.user_id,
            membership.role,
        )
        messages.error(request, _('You do not have permission to remove this member.'))
        return redirect(reverse('shop-garage-members', args=[garage.pk]))

    if membership.role == GarageMembership.ROLE_OWNER:
        owner_count = garage.memberships.filter(role=GarageMembership.ROLE_OWNER).count()
        if owner_count <= 1:
            messages.error(request, _('Cannot remove the last owner of the fleet.'))
            return redirect(reverse('shop-garage-members', args=[garage.pk]))

    target_user_id = membership.user_id
    target_role = membership.role
    membership.delete()
    security_log.info(
        'member_removed: user=%s garage=%s target_user=%s target_role=%s',
        request.user.pk,
        garage.pk,
        target_user_id,
        target_role,
    )
    messages.success(request, _('Member removed successfully.'))
    return redirect(reverse('shop-garage-members', args=[garage.pk]))


@hanko_login_required
@require_POST
@require_garage_permission(
    'can_manage_members',
    message=_('You do not have permission to manage fleet invitations.'),
)
def garage_invitation_cancel(request: HttpRequest, pk: str, invitation_pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    invitation = get_object_or_404(garage.invitations, pk=invitation_pk)
    if invitation.status != GarageInvitation.STATUS_PENDING:
        messages.info(request, _('This invitation is no longer active.'))
        return redirect(reverse('shop-garage-share', args=[garage.pk]))

    invitation.status = GarageInvitation.STATUS_CANCELLED
    invitation.save(update_fields=['status', 'updated_at'])
    messages.success(request, _('Invitation to %(email)s cancelled.') % {'email': invitation.invited_email})
    return redirect(reverse('shop-garage-share', args=[garage.pk]))


@hanko_login_required
@require_garage_permission(
    'can_manage_members',
    message=_('You do not have permission to import data into this fleet.'),
    log_reason='garage_import_not_manager',
)
def garage_import(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)

    if request.method == 'POST':
        form = GarageImportForm(request.POST, request.FILES)
        if form.is_valid():
            importer = CSVImporter()
            uploaded_file = form.cleaned_data['import_file']
            dry_run = form.cleaned_data['dry_run']
            try:
                records = importer.parse_csv_bytes(uploaded_file.read(), source_name=uploaded_file.name)
                result = importer.import_records(
                    importer.resolve_model('car'),
                    records,
                    context=ImportContext(garage=garage, user=request.user),
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
                    form.add_error('import_file', _('Import validation failed. Fix the file and try again.'))
                else:
                    if dry_run:
                        messages.success(
                            request,
                            _('Dry run complete for %(model)s: %(count)s records validated.') % {'model': result.model_label, 'count': result.created_count},
                        )
                    else:
                        messages.success(
                            request,
                            _('Imported %(count)s records into %(garage)s.') % {'count': result.created_count, 'garage': garage.name},
                        )
                        return redirect(reverse('shop-garage-detail', args=[garage.pk]))
    else:
        form = GarageImportForm()

    return render(
        request,
        'shop/fleet_import.html',
        {
            'form': form,
            'garage': garage,
            'title': _('Import cars into %(name)s') % {'name': garage.name},
            'subtitle': _('Upload normalized CSV for cars assigned to this fleet'),
        },
    )


@hanko_login_required
@require_garage_permission(
    'can_manage_members',
    message=_('You do not have permission to export data from this fleet.'),
    log_reason='garage_export_not_manager',
)
def garage_export(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    workbook = export_garage_to_excel(garage)
    response = HttpResponse(
        workbook.content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{workbook.filename}"'
    return response


