"""Test-only URL configuration.

Extends the production URLconf with the DEBUG-only test-session helper used by
the Selenium end-to-end suite. This keeps the helper out of the production
URL configuration while still making it available to pytest and ``make test-e2e``.
"""

from django.urls import include, path

from settings.urls import urlpatterns
from shop import views

urlpatterns = urlpatterns + [
    path('set-test-session/', views.set_test_session, name='shop-set-test-session'),
]
