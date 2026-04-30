from http import HTTPStatus

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_home_uses_default_template(client):
    response = client.get(reverse("home"))

    assert response.status_code == HTTPStatus.OK
    assert "pages/home.html" in [template.name for template in response.templates]
