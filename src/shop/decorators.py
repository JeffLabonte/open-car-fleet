import logging
from functools import wraps
from typing import Any, Callable

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from shop.permissions import GarageSharingPermissions

security_log = logging.getLogger('security')


def require_garage_permission(
    permission: str,
    *,
    fallback_url_name: str = 'shop-garage-detail',
    message: str | None = None,
    log_reason: str | None = None,
) -> Callable[..., Callable[..., HttpResponse]]:
    """Require a specific garage permission for the view.

    The decorated view must receive the garage primary key as ``pk``.
    On denial the user is redirected to ``fallback_url_name`` (default:
    ``shop-garage-detail``) with an error message.

    If ``log_reason`` is provided, a security audit log line is emitted when
    access is denied.
    """

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            # Lazy import to avoid a circular dependency between decorators and
            # view_helpers (which imports from shop.permissions).
            from shop.view_helpers import user_garages_queryset

            pk = kwargs.get('pk')
            garage = get_object_or_404(user_garages_queryset(request.user), pk=pk)
            perms = GarageSharingPermissions(request.user, garage)

            if not getattr(perms, permission, False):
                if log_reason:
                    security_log.warning(
                        'access_denied: user=%s path=%s reason=%s garage=%s',
                        request.user.pk,
                        request.path,
                        log_reason,
                        garage.pk,
                    )
                messages.error(
                    request,
                    message or _('You do not have permission to access this page.'),
                )
                return redirect(reverse(fallback_url_name, args=[garage.pk]))

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator
