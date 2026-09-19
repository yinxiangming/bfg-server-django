from django.test import Client


def test_health_endpoint_is_public_and_tenant_independent():
    response = Client().get('/api/v1/health/')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
