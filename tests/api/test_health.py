from tests.api.support import api_client


def test_health_endpoint_returns_ok() -> None:
    with api_client() as (client, _repository):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
