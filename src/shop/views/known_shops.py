import logging

from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from shop.forms import (
    CarForm,
    CarImportForm,
    CarPartForm,
    FleetForm,
    FleetInviteForm,
    FleetMembershipRoleForm,
    KnownShopForm,
    KnownShopProofForm,
    ReportForm,
    WorkJobForm,
)
from shop.middleware import hanko_login_required
from shop.services.attachments import save_attachments
from shop.view_helpers import (
    user_can_manage_fleet,
    user_can_manage_known_shop,
    user_cars_queryset,
    user_fleets_queryset,
    user_known_shops_queryset,
)
from shop.views.helpers import handle_model_form

security_log = logging.getLogger('security')

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
    def _set_creator(shop: KnownShop, _form) -> None:
        shop.created_by = request.user

    return handle_model_form(
        request,
        KnownShopForm,
        'shop/shop_form.html',
        lambda shop: reverse('shop-known-shop-detail', args=[shop.pk]),
        save_callback=_set_creator,
        success_message=_('Shop added successfully.'),
        context={
            'title': _('Add known shop'),
            'subtitle': _('Save a shop now and add supporting proofs over time'),
        },
    )


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
        security_log.warning(
            'access_denied: user=%s path=%s reason=known_shop_proof_not_manager shop=%s',
            request.user.pk,
            request.path,
            shop.pk,
        )
        messages.error(request, _('You do not have permission to add proof for this shop.'))
        return redirect(reverse('shop-known-shop-list'))
    if request.method == 'POST':
        form = KnownShopProofForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                proof = form.save(commit=False)
                proof.shop = shop
                proof.save()
                save_attachments(
                    proof,
                    form.cleaned_data.get('attachments', []),
                    [],
                    staged=form.cleaned_data.get('staged_attachments'),
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


