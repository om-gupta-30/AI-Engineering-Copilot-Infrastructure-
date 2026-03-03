"""
Smoke test: health endpoint returns 200 and expected payload.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from ai_copilot_infra.api.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_ok(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
