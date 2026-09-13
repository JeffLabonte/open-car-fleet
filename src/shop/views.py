import json
import mimetypes
import os
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import logout
from django.middleware.csrf import get_token
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.utils.translation import gettext as _

from shop.auth import HankoAuthenticationError, complete_hanko_login, fetch_hanko_userinfo
from shop.exporters import export_garage_to_excel
from shop.forms import (
    CarImportForm,
    CarCreateForm,
    CarPartForm,
    CarUpdateForm,
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
from car_docs.models import CarDoc
from shop.middleware import hanko_login_required
from shop.models.attachment import Attachment
from shop.models.car import CarPart
from shop.models.garage import GarageInvitation, GarageMembership, KnownShop, KnownShopProof
from shop.models.job import WorkJob
from shop.models.report import Report
from shop.permissions import GarageSharingPermissions, get_membership_or_404
from shop.view_helpers import (
    save_attachments,
    user_can_manage_garage,
    user_can_manage_known_shop,
    user_cars_queryset,
    user_garages_queryset,
    user_known_shops_queryset,
)

# Content types that are safe to render inline in the browser. Anything else
# (e.g. text/html disguised with a trusted extension) is served as a download.
INLINE_SAFE_ATTACHMENT_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'video/mp4',
    'video/webm',
    'video/quicktime',
    'application/pdf',
}


def get_theme_from_request(request: HttpRequest) -> str:
    cookie_theme = request.COOKIES.get('theme', '').lower()
    if cookie_theme in {'light', 'dark'}:
        return cookie_theme
    return 'light'


def safe_next_url(request: HttpRequest, default: str = '/') -> str:
    """Return a local, scheme-safe redirect target from ?next=, else the default."""
    candidate = request.GET.get('next', default) or default
    if url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


def login_view(request: HttpRequest) -> HttpResponse:
    # Always seed a CSRF cookie for the active session so POST-based logout
    # requests from trusted origins can validate even when this page redirects a
    # signed-in user away from the login form.
    get_token(request)

    if request.user.is_authenticated:
        return redirect(reverse('shop-index'))

    # One-time logout marker prevents stale query params from re-triggering
    # frontend logout behavior after users sign back in.
    logged_out = bool(request.session.pop('logged_out', False))

    return render(request, 'shop/login.html', {
        'title': _('Login'),
        'subtitle': _('Authenticate with Hanko to continue'),
            'hanko_api_url': getattr(settings, 'HANKO_API_URL', ''),
        'next_url': safe_next_url(request),
        'logged_out': logged_out,
        'theme': get_theme_from_request(request),
    })


def theme_view(request: HttpRequest, theme: str) -> HttpResponse:
    normalized_theme = theme.lower() if isinstance(theme, str) else 'light'
    if normalized_theme not in {'light', 'dark'}:
        normalized_theme = 'light'

    response = redirect(safe_next_url(request, default=reverse('shop-index')))
    response.set_cookie('theme', normalized_theme, max_age=60 * 60 * 24 * 365, httponly=False, samesite='Lax')
    response.cookies['theme']['max-age'] = '31536000'
    return response


@require_GET
def set_test_session(request: HttpRequest) -> HttpResponse:
    """DEBUG-only helper that signs a user in by email for Selenium suites.

    The session is created without a Hanko session token, so the
    authentication middleware skips Hanko revalidation for these browser
    sessions. The endpoint is disabled entirely outside DEBUG mode.
    """
    if not getattr(settings, 'DEBUG', False):
        raise Http404(_('Not found.'))

    email = (request.GET.get('email') or '').strip().lower()
    if not email or '@' not in email or len(email) > 254:
        return JsonResponse({'ok': False, 'error': 'A valid email is required.'}, status=400)

    complete_hanko_login(request, {
        'id': f'e2e-{email}',
        'email': email,
        'name': email.split('@')[0],
        'provider': 'local',
    })
    return redirect(safe_next_url(request, default=reverse('shop-index')))


def hanko_callback(request: HttpRequest) -> JsonResponse:
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Method not allowed'}, status=405)

    raw_payload: Any
    try:
        raw_payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        raw_payload = {}

    payload: dict[str, Any] = cast(dict[str, Any], raw_payload) if isinstance(raw_payload, dict) else {}
    raw_session_token = payload.get('session_token')
    session_token = raw_session_token.strip() if isinstance(raw_session_token, str) else ''

    if not payload:
        return JsonResponse({'ok': False, 'error': 'Missing user payload'}, status=400)
    if not session_token:
        return JsonResponse({'ok': False, 'error': 'Missing session token'}, status=400)

    try:
        user_data = fetch_hanko_userinfo(session_token)
    except HankoAuthenticationError:
        return JsonResponse({'ok': False, 'error': 'Invalid Hanko session'}, status=401)

    user = complete_hanko_login(request, user_data)
    request.session['hanko_session_token'] = session_token
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
    form = GarageMembershipRoleForm(request.POST, allowed_roles=perms.can_change_role_to)
    if form.is_valid():
        new_role = form.cleaned_data['role']
        if membership.role == GarageMembership.ROLE_OWNER and new_role != GarageMembership.ROLE_OWNER:
            owner_count = garage.memberships.filter(role=GarageMembership.ROLE_OWNER).count()
            if owner_count <= 1:
                messages.error(request, _('Cannot remove the last owner of the fleet.'))
                return redirect(reverse('shop-garage-members', args=[garage.pk]))
        membership.role = new_role
        membership.save(update_fields=['role', 'updated_at'])
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
    if membership.role == GarageMembership.ROLE_OWNER:
        owner_count = garage.memberships.filter(role=GarageMembership.ROLE_OWNER).count()
        if owner_count <= 1:
            messages.error(request, _('Cannot remove the last owner of the fleet.'))
            return redirect(reverse('shop-garage-members', args=[garage.pk]))

    membership.delete()
    messages.success(request, _('Member removed successfully.'))
    return redirect(reverse('shop-garage-members', args=[garage.pk]))


@hanko_login_required
def garage_import(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    if not user_can_manage_garage(request.user, garage):
        messages.error(request, _('You do not have permission to import data into this fleet.'))
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

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
def garage_export(request: HttpRequest, pk: str) -> HttpResponse:
    garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
    if not user_can_manage_garage(request.user, garage):
        messages.error(request, _('You do not have permission to export data from this fleet.'))
        return redirect(reverse('shop-garage-detail', args=[garage.pk]))

    workbook = export_garage_to_excel(garage)
    response = HttpResponse(
        workbook.content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{workbook.filename}"'
    return response


@hanko_login_required
def known_shop_list(request: HttpRequest) -> HttpResponse:
    shops = user_known_shops_queryset(request.user).prefetch_related('proofs').order_by('name')
    return render(request, 'shop/shop_list.html', {
        'shops': shops,
        'title': _('Known shops'),
        'subtitle': _('Keep trusted repair shops and their supporting proofs together'),
    })


@hanko_login_required
def known_shop_create(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = KnownShopForm(request.POST)
        if form.is_valid():
            shop = form.save(commit=False)
            shop.created_by = request.user
            shop.save()
            messages.success(request, _('Shop added successfully.'))
            return redirect(reverse('shop-known-shop-detail', args=[shop.pk]))
    else:
        form = KnownShopForm()
    return render(request, 'shop/shop_form.html', {
        'form': form,
        'is_create': True,
        'title': _('Add known shop'),
        'subtitle': _('Save a shop now and add supporting proofs over time'),
    })


@hanko_login_required
def known_shop_detail(request: HttpRequest, pk: int) -> HttpResponse:
    shop = get_object_or_404(user_known_shops_queryset(request.user).prefetch_related('proofs'), pk=pk)
    return render(request, 'shop/shop_detail.html', {
        'shop': shop,
        'title': shop.name,
        'subtitle': _('Shop details and supporting proofs'),
    })


@hanko_login_required
def known_shop_proof_create(request: HttpRequest, shop_pk: int) -> HttpResponse:
    shop = get_object_or_404(user_known_shops_queryset(request.user), pk=shop_pk)
    if not user_can_manage_known_shop(request.user, shop):
        messages.error(request, _('You do not have permission to add proof for this shop.'))
        return redirect(reverse('shop-known-shop-list'))
    if request.method == 'POST':
        form = KnownShopProofForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                proof = form.save(commit=False)
                proof.shop = shop
                proof.save()
                save_attachments(
                    proof,
                    form.cleaned_data.get('attachments', []),
                    [],
                )
            messages.success(request, _('Proof added successfully.'))
            return redirect(reverse('shop-known-shop-detail', args=[shop.pk]))
    else:
        form = KnownShopProofForm()
    return render(request, 'shop/shop_proof_form.html', {
        'form': form,
        'shop': shop,
        'title': _('Add proof for %(name)s') % {'name': shop.name},
        'subtitle': _('Add a document or notes supporting this shop'),
    })


@hanko_login_required
def car_import(request: HttpRequest, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not user_can_manage_garage(request.user, car.garage):
        messages.error(request, _('You do not have permission to import data into this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))

    if request.method == 'POST':
        form = CarImportForm(request.POST, request.FILES)
        if form.is_valid():
            importer = CSVImporter()
            uploaded_file = form.cleaned_data['import_file']
            dry_run = form.cleaned_data['dry_run']
            try:
                model = importer.resolve_model(form.cleaned_data['import_type'])
                records = importer.parse_csv_bytes(uploaded_file.read(), source_name=uploaded_file.name)
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
                    messages.warning(request, _('Record %(number)s: %(message)s') % {'number': warning.record_number, 'message': warning.message})

                if result.has_errors:
                    for error in result.errors:
                        messages.error(request, _('Record %(number)s: %(message)s') % {'number': error.record_number, 'message': error.message})
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
                            _('Imported %(count)s records for %(car)s.') % {'count': result.created_count, 'car': car.usual_name or car.make},
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
            'title': _('Import records for %(name)s') % {'name': car.usual_name or car.make},
            'subtitle': _('Upload normalized CSV for work jobs or reports tied to this car'),
        },
    )


def _render_invitation_response(request: HttpRequest, invitation: GarageInvitation) -> HttpResponse:
    return render(
        request,
        'shop/fleet_invitation_accept.html',
        {
            'invitation': invitation,
            'title': _('Accept fleet invitation'),
            'subtitle': invitation.garage.name,
        },
    )


@hanko_login_required
def garage_invitation_accept(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        GarageInvitation.objects.select_related('garage'),
        token=token,
    )

    if invitation.status != GarageInvitation.STATUS_PENDING:
        messages.info(request, _('This invitation is no longer active.'))
        return redirect(reverse('shop-index'))

    if invitation.is_expired:
        invitation.status = GarageInvitation.STATUS_EXPIRED
        invitation.save(update_fields=['status', 'updated_at'])
        messages.error(request, _('This invitation has expired.'))
        return redirect(reverse('shop-index'))

    user_email = (request.user.email or '').strip().lower()
    invited_email = invitation.invited_email.strip().lower()
    if not user_email or user_email != invited_email:
        messages.error(
            request,
            _("Sign in with %(email)s to accept this invitation.") % {'email': invitation.invited_email},
        )
        return redirect(reverse('shop-index'))

    if request.method != 'POST':
        return _render_invitation_response(request, invitation)

    with transaction.atomic():
        membership, created = GarageMembership.objects.get_or_create(
            garage=invitation.garage,
            user=request.user,
            defaults={'role': invitation.role},
        )
        if not created:
            membership.role = invitation.role
            membership.save(update_fields=['role', 'updated_at'])
        invitation.status = GarageInvitation.STATUS_ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = request.user
        invitation.save(update_fields=['status', 'accepted_at', 'accepted_by', 'updated_at'])

    if created:
        messages.success(request, _("You have joined '%(fleet)s'.") % {'fleet': invitation.garage.name})
    else:
        messages.info(request, _("You are already a member of '%(fleet)s'.") % {'fleet': invitation.garage.name})
    return redirect(reverse('shop-garage-detail', args=[invitation.garage.pk]))


@hanko_login_required
@require_POST
def garage_invitation_decline(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        GarageInvitation.objects.select_related('garage'),
        token=token,
    )

    if invitation.status != GarageInvitation.STATUS_PENDING:
        messages.info(request, _('This invitation is no longer active.'))
        return redirect(reverse('shop-index'))

    if invitation.is_expired:
        invitation.status = GarageInvitation.STATUS_EXPIRED
        invitation.save(update_fields=['status', 'updated_at'])
        messages.error(request, _('This invitation has expired.'))
        return redirect(reverse('shop-index'))

    user_email = (request.user.email or '').strip().lower()
    invited_email = invitation.invited_email.strip().lower()
    if not user_email or user_email != invited_email:
        messages.error(
            request,
            _("Sign in with %(email)s to decline this invitation.") % {'email': invitation.invited_email},
        )
        return redirect(reverse('shop-index'))

    invitation.status = GarageInvitation.STATUS_DECLINED
    invitation.declined_at = timezone.now()
    invitation.declined_by = request.user
    invitation.save(update_fields=['status', 'declined_at', 'declined_by', 'updated_at'])
    messages.info(request, _('Invitation declined.'))
    return redirect(reverse('shop-index'))


@hanko_login_required
def car_list(request: HttpRequest) -> HttpResponse:
    """Display list of cars with basic info."""
    cars = user_cars_queryset(request.user).order_by('-created_at')
    return render(request, 'shop/car_list.html', {'cars': cars, 'can_edit_garage_data': True})


@hanko_login_required
@require_POST
def car_delete(request: HttpRequest, pk: str) -> HttpResponse:
    """Delete a car from a garage the user can manage."""
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not user_can_manage_garage(request.user, car.garage):
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
        form = CarCreateForm(request.POST, user=request.user)
        if form.is_valid():
            garage = form.cleaned_data.get('garage')
            if garage is not None and not GarageSharingPermissions(request.user, garage).can_edit_garage_data:
                messages.error(request, _('You do not have permission to add a car to this fleet.'))
                return redirect(reverse('shop-car-list'))
            car = form.save()
            messages.success(request, _('Car created successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarCreateForm(user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': True})


@hanko_login_required
def car_update(request: HttpRequest, pk: str) -> HttpResponse:
    """Update an existing Car. Preserves CSRF protection via template token."""
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to edit this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = CarUpdateForm(request.POST, instance=car, user=request.user)
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
        form = CarUpdateForm(instance=car, user=request.user)
    return render(request, 'shop/car_form.html', {'form': form, 'is_create': False, 'car': car})


@hanko_login_required
def part_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add parts to this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = CarPartForm(request.POST)
        if form.is_valid():
            part = form.save(commit=False)
            part.car = car
            part.save()
            messages.success(request, _('Part status added successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarPartForm()
    return render(request, 'shop/part_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def part_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update parts for this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    part = get_object_or_404(CarPart, pk=pk, car=car)
    if request.method == 'POST':
        form = CarPartForm(request.POST, instance=part)
        if form.is_valid():
            form.save()
            messages.success(request, _('Part status updated successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = CarPartForm(instance=part)
    return render(request, 'shop/part_form.html', {'form': form, 'is_create': False, 'car': car, 'part': part})


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


def _user_can_view_attachment(user: Any, attachment: Attachment) -> bool:
    """Authorize attachment downloads through their parent object's permissions."""
    parent = attachment.parent
    if parent is None:
        return False
    if isinstance(parent, Report):
        return user_cars_queryset(user).filter(pk=parent.car_id).exists()
    if isinstance(parent, CarDoc):
        from shop.view_helpers import user_car_docs_queryset
        return user_car_docs_queryset(user).filter(pk=parent.pk).exists()
    if isinstance(parent, KnownShopProof):
        return user_known_shops_queryset(user).filter(pk=parent.shop_id).exists()
    return False


@hanko_login_required
@require_GET
def attachment_file(request: HttpRequest, pk: int) -> FileResponse:
    attachment = get_object_or_404(Attachment.objects.select_related('content_type'), pk=pk)
    if not _user_can_view_attachment(request.user, attachment):
        raise Http404(_('Attachment not found.'))
    if not attachment.file:
        raise Http404(_('Attachment has no file.'))
    content_type = mimetypes.guess_type(attachment.file.name)[0] or 'application/octet-stream'
    response = FileResponse(attachment.file.open('rb'), content_type=content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    if content_type not in INLINE_SAFE_ATTACHMENT_TYPES:
        download_name = os.path.basename(attachment.file.name).replace('"', '')
        response['Content-Disposition'] = f'attachment; filename="{download_name}"'
    return response


@hanko_login_required
def report_create(request: HttpRequest, car_pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to add reports to this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    if request.method == 'POST':
        form = ReportForm(request.POST, request.FILES, user=request.user, garage=car.garage)
        if form.is_valid():
            with transaction.atomic():
                report = form.save(commit=False)
                report.car = car
                report.save()
                save_attachments(
                    report,
                    form.cleaned_data.get('attachments', []),
                    form.cleaned_data.get('external_links', []),
                )
            messages.success(request, _('Maintenance report added successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm(user=request.user, garage=car.garage)
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': True, 'car': car})


@hanko_login_required
def report_update(request: HttpRequest, car_pk: str, pk: str) -> HttpResponse:
    car = get_object_or_404(user_cars_queryset(request.user).select_related('garage'), pk=car_pk)
    if not GarageSharingPermissions(request.user, car.garage).can_edit_garage_data:
        messages.error(request, _('You do not have permission to update reports for this car.'))
        return redirect(reverse('shop-car-detail', args=[car.pk]))
    report = get_object_or_404(Report, pk=pk, car=car)
    if request.method == 'POST':
        form = ReportForm(request.POST, request.FILES, instance=report, user=request.user, garage=car.garage)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                save_attachments(
                    report,
                    form.cleaned_data.get('attachments', []),
                    form.cleaned_data.get('external_links', []),
                )
            messages.success(request, _('Maintenance report updated successfully.'))
            return redirect(reverse('shop-car-detail', args=[car.pk]))
    else:
        form = ReportForm(instance=report, user=request.user, garage=car.garage)
    return render(request, 'shop/report_form.html', {'form': form, 'is_create': False, 'car': car, 'report': report})


def logout_view(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        logout(request)
        request.session['logged_out'] = True
        messages.success(request, _('Logged out successfully.'))
    return redirect(reverse('shop-login'))
