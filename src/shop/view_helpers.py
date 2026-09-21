import os
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from shop.models.attachment import Attachment
from shop.models.car import Car
from shop.models.garage import Garage, KnownShop
from shop.permissions import GarageSharingPermissions


def user_cars_queryset(user: Any):
    return Car.objects.filter(garage__members=user).distinct()


def user_garages_queryset(user: Any):
    return Garage.objects.filter(members=user).distinct()


def user_car_docs_queryset(user: Any):
    from car_docs.models import CarDoc
    return CarDoc.objects.filter(car__garage__members=user).distinct()


def save_attachments(
    parent: Any,
    uploaded_files: list[Any],
    external_links: list[str],
    staged: list[Any] | None = None,
) -> None:
    """Persist unified attachments (uploads and external links) for any parent model.

    ``staged`` holds Attachment rows created earlier by the AJAX upload
    endpoint for this user (validated in the form); they are re-parented
    onto ``parent`` here.
    """
    content_type = ContentType.objects.get_for_model(parent)
    for index, uploaded_file in enumerate(uploaded_files):
        Attachment.objects.create(
            content_type=content_type,
            object_id=str(parent.pk),
            source_type=Attachment.SOURCE_UPLOAD,
            file=uploaded_file,
            display_name=os.path.basename(getattr(uploaded_file, 'name', '') or f'attachment-{index + 1}'),
            mime_type=getattr(uploaded_file, 'content_type', ''),
        )

    for index, attachment in enumerate(staged or []):
        attachment.content_type = content_type
        attachment.object_id = str(parent.pk)
        attachment.order = len(uploaded_files) + index
        attachment.save()

    for index, external_link in enumerate(external_links):
        attachment = Attachment(
            content_type=content_type,
            object_id=str(parent.pk),
            source_type=Attachment.SOURCE_EXTERNAL,
            url=external_link,
            display_name=external_link.rstrip('/').rsplit('/', 1)[-1] or f'link-{index + 1}',
            kind=Attachment.KIND_LINK,
        )
        attachment.full_clean()
        attachment.save()


def user_can_manage_garage(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).can_manage_members


def user_can_edit_garage_data(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).can_edit_garage_data


def user_can_view_garage(user: Any, garage: Garage) -> bool:
    return GarageSharingPermissions(user, garage).can_view_garage


def user_known_shops_queryset(user: Any):
    """Return unowned directory entries and shops owned by the user."""
    return KnownShop.objects.filter(Q(created_by__isnull=True) | Q(created_by=user)).distinct()


def user_can_manage_known_shop(user: Any, shop: KnownShop) -> bool:
    return bool(getattr(user, 'is_staff', False) or shop.created_by_id == getattr(user, 'pk', None))
