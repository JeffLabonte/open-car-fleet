
from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from shop.middleware import hanko_login_required
from shop.models.fleet import Fleet, FleetInvitation, FleetMembership, KnownShop, KnownShopProof

def _render_invitation_response(request: HttpRequest, invitation: FleetInvitation) -> HttpResponse:
    return render(
        request,
        'shop/fleet_invitation_accept.html',
        {
            'invitation': invitation,
            'title': _('Accept fleet invitation'),
            'subtitle': invitation.fleet.name,
        },
    )


@hanko_login_required
def fleet_invitation_accept(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        FleetInvitation.objects.select_related('fleet'),
        token=token,
    )

    if invitation.status != FleetInvitation.STATUS_PENDING:
        messages.info(request, _('This invitation is no longer active.'))
        return redirect(reverse('shop-index'))

    if invitation.is_expired:
        invitation.status = FleetInvitation.STATUS_EXPIRED
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
        membership, created = FleetMembership.objects.get_or_create(
            fleet=invitation.fleet,
            user=request.user,
            defaults={'role': invitation.role},
        )
        if not created:
            membership.role = invitation.role
            membership.save(update_fields=['role', 'updated_at'])
        invitation.status = FleetInvitation.STATUS_ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = request.user
        invitation.save(update_fields=['status', 'accepted_at', 'accepted_by', 'updated_at'])

    if created:
        messages.success(request, _("You have joined '%(fleet)s'.") % {'fleet': invitation.fleet.name})
    else:
        messages.info(request, _("You are already a member of '%(fleet)s'.") % {'fleet': invitation.fleet.name})
    return redirect(reverse('shop-fleet-detail', args=[invitation.fleet.pk]))


@hanko_login_required
@require_POST
def fleet_invitation_decline(request: HttpRequest, token: str) -> HttpResponse:
    invitation = get_object_or_404(
        FleetInvitation.objects.select_related('fleet'),
        token=token,
    )

    if invitation.status != FleetInvitation.STATUS_PENDING:
        messages.info(request, _('This invitation is no longer active.'))
        return redirect(reverse('shop-index'))

    if invitation.is_expired:
        invitation.status = FleetInvitation.STATUS_EXPIRED
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

    invitation.status = FleetInvitation.STATUS_DECLINED
    invitation.declined_at = timezone.now()
    invitation.declined_by = request.user
    invitation.save(update_fields=['status', 'declined_at', 'declined_by', 'updated_at'])
    messages.info(request, _('Invitation declined.'))
    return redirect(reverse('shop-index'))


