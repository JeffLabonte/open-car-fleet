# Domain-specific view modules.
# This package re-exports all view functions so existing imports keep working.

# Backwards-compatible re-exports for tests/code that patch these names on shop.views.
from shop.services.attachments import (
    ATTACHMENT_USER_STAGED_QUOTA_BYTES,
    INLINE_SAFE_ATTACHMENT_TYPES,
    STAGED_ATTACHMENT_MAX_AGE,
    purge_stale_staged_attachments,
    save_attachments,
)
from shop.services.invitations import expire_stale_pending_invitations

from shop.views.attachments import (
    _user_can_view_attachment,
    attachment_delete,
    attachment_file,
    attachment_upload,
)

from shop.views.auth import (
    get_theme_from_request,
    hanko_callback,
    login_view,
    logout_view,
    profile_view,
    safe_next_url,
    set_test_session,
    theme_view,
)

from shop.views.car import (
    car_create,
    car_delete,
    car_detail,
    car_import,
    car_list,
    car_update,
    part_create,
    part_update,
    report_create,
    report_update,
    workjob_create,
    workjob_update,
)

from shop.views.garage import (
    garage_create,
    garage_detail,
    garage_export,
    garage_import,
    garage_invitation_cancel,
    garage_member_remove,
    garage_member_role,
    garage_members,
    garage_share,
    garage_update,
    index,
)

from shop.views.invitations import (
    _render_invitation_response,
    garage_invitation_accept,
    garage_invitation_decline,
)

from shop.views.known_shops import (
    known_shop_create,
    known_shop_detail,
    known_shop_list,
    known_shop_proof_create,
)

__all__ = [
    'INLINE_SAFE_ATTACHMENT_TYPES',
    'STAGED_ATTACHMENT_MAX_AGE',
    '_render_invitation_response',
    '_user_can_view_attachment',
    'attachment_delete',
    'attachment_file',
    'attachment_upload',
    'car_create',
    'car_delete',
    'car_detail',
    'car_import',
    'car_list',
    'car_update',
    'garage_create',
    'garage_detail',
    'garage_export',
    'garage_import',
    'garage_invitation_accept',
    'garage_invitation_cancel',
    'garage_invitation_decline',
    'garage_member_remove',
    'garage_member_role',
    'garage_members',
    'garage_share',
    'garage_update',
    'get_theme_from_request',
    'hanko_callback',
    'index',
    'known_shop_create',
    'known_shop_detail',
    'known_shop_list',
    'known_shop_proof_create',
    'login_view',
    'logout_view',
    'part_create',
    'part_update',
    'profile_view',
    'expire_stale_pending_invitations',
    'purge_stale_staged_attachments',
    'report_create',
    'report_update',
    'safe_next_url',
    'set_test_session',
    'theme_view',
    'workjob_create',
    'workjob_update',
]
