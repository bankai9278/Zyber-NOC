"""Tests for the starter health route."""


def test_health_route_reports_the_app_is_running(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.is_json

    body = response.get_json()
    assert body["status"] == "ok"
    assert body["application"] == "zyber-noc"
