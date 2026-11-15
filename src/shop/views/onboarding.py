from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from shop.forms.onboarding import OnboardingForm
from shop.middleware import hanko_login_required
from shop.views.auth import safe_next_url


@hanko_login_required
def welcome_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    if getattr(user, "onboarding_completed", False):
        stored_next = request.session.pop("post_onboarding_redirect", None)
        return redirect(safe_next_url(request, default=reverse("shop-index"), candidate=stored_next))

    # Preserve a ``next`` target supplied via the query string through the form POST.
    query_next = request.GET.get("next")
    if query_next:
        request.session["post_onboarding_redirect"] = safe_next_url(
            request, default=reverse("shop-index"), candidate=query_next
        )
        request.session.save()

    if request.method == "POST":
        form = OnboardingForm(request.POST)
        if form.is_valid():
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.username = form.build_username()
            user.is_mechanic = form.cleaned_data["is_mechanic"]
            if user.is_mechanic:
                user.mechanic_promoted_at = timezone.now()
            user.onboarding_completed = True
            user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "username",
                    "is_mechanic",
                    "mechanic_promoted_at",
                    "onboarding_completed",
                ]
            )
            messages.success(request, _("Welcome! Your profile is ready."))
            stored_next = request.session.pop("post_onboarding_redirect", None)
            return redirect(safe_next_url(request, default=reverse("shop-index"), candidate=stored_next))
    else:
        form = OnboardingForm(
            initial={
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
        )

    return render(
        request,
        "shop/onboarding.html",
        {
            "title": _("Welcome"),
            "subtitle": _("Let’s finish setting up your account."),
            "form": form,
        },
    )
