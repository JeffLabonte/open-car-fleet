from django.test import Client
from django.urls import reverse
from pytest_bdd import given, scenarios, then, when


scenarios('features/protected_pages.feature')


@given('an anonymous test client', target_fixture='anonymous_client')
def anonymous_client() -> Client:
    return Client()


@when('the client requests the car list', target_fixture='car_list_response')
def request_car_list(anonymous_client: Client):
    return anonymous_client.get(reverse('shop-car-list'))


@then('the response redirects to the login page')
def response_redirects_to_login(car_list_response):
    assert car_list_response.status_code == 302
    assert car_list_response.url.startswith(f'{reverse("shop-login")}?next=')
