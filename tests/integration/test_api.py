"""Integration test for POST /new_pod_run_model.

The lifespan (Redis connection, worker task) is bypassed with mocks so this
test runs without a real Redis or Docker. It verifies that the HTTP layer
wires together correctly: request deserialization → payload enrichment →
queue push → response serialization.
"""
import base64
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport


@asynccontextmanager
async def mock_lifespan(app):
    """Replace the real lifespan to avoid Redis + worker startup in tests."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.zadd = AsyncMock(return_value=1)
    mock_redis.zremrangebyscore = AsyncMock(return_value=0)
    mock_redis.aclose = AsyncMock()

    mock_queue = AsyncMock()
    mock_queue.push = AsyncMock(return_value=1.5)  # 1.5ms push latency
    mock_queue.close = AsyncMock()

    app.state.redis = mock_redis
    app.state.queue = mock_queue
    yield


@pytest.fixture
async def client():
    from app.main import app

    # Patch the lifespan so it populates app.state with mocks instead of
    # real Redis/worker. ASGITransport does not trigger lifespan automatically,
    # so we also pre-seed app.state directly to cover both paths.
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.zadd = AsyncMock(return_value=1)
    mock_redis.zremrangebyscore = AsyncMock(return_value=0)
    mock_redis.aclose = AsyncMock()

    mock_queue = AsyncMock()
    mock_queue.push = AsyncMock(return_value=1.5)  # 1.5ms push latency
    mock_queue.close = AsyncMock()

    app.state.redis = mock_redis
    app.state.queue = mock_queue
    app.router.lifespan_context = mock_lifespan

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestReceiveData:
    @pytest.mark.asyncio
    async def test_returns_queued_status(self, client):
        image_b64 = base64.b64encode(b"fake_image_bytes").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64, "scenario": "test_scenario"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

    @pytest.mark.asyncio
    async def test_returns_correct_scenario(self, client):
        image_b64 = base64.b64encode(b"fake").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64, "scenario": "my_scenario"},
        )
        assert response.json()["scenario"] == "my_scenario"

    @pytest.mark.asyncio
    async def test_default_scenario(self, client):
        image_b64 = base64.b64encode(b"fake").decode()
        response = await client.post(
            "/new_pod_run_model",
            json={"image": image_b64},
        )
        assert response.status_code == 200
        assert response.json()["scenario"] == "default"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
