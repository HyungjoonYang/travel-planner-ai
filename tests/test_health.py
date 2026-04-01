def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_check_version(client):
    response = client.get("/health")
    assert response.json()["version"] == "0.1.0"
