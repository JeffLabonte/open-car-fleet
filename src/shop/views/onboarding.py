from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from shop.forms.onboarding import OnboardingForm
from shop.middleware import hanko_login_required


@hanko_login_required
def welcome_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    if getattr(user, "onboarding_completed", False):
        return redirect(reverse("shop-index"))

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
            return redirect(reverse("shop-index"))
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
