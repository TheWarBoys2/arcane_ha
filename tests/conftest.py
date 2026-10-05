"""Fixtures: a fake Arcane server behind aioclient_mock."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from homeassistant.const import CONF_API_KEY, CONF_URL, CONF_VERIFY_SSL
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arcane.const import DOMAIN

URL = "http://arcane.example:3552"
API = URL + "/api"

ENVIRONMENTS = {
    "success": True,
    "data": [
        {"id": "0", "name": "Main", "status": "online", "enabled": True, "apiUrl": ""},
        {"id": "abc", "name": "Remote", "status": "offline", "enabled": True, "apiUrl": "http://remote:3553"},
    ],
    "pagination": {"totalItems": 2, "totalPages": 1, "currentPage": 1, "itemsPerPage": 100},
}

CONTAINERS = {
    "success": True,
    "data": [
        {
            "id": "aaa111",
            "names": ["/web"],
            "image": "nginx:latest",
            "state": "running",
            "status": "Up 3 hours (healthy)",
            "labels": {"com.docker.compose.project": "web"},
            "updateInfo": {"hasUpdate": True, "currentVersion": "1.32.0", "latestVersion": "1.33.0"},
            "resourceSample": {"cpuPercent": 1.234, "memoryUsageBytes": 52428800, "memoryLimitBytes": 8589934592},
        },
        {
            "id": "bbb222",
            "names": ["/db"],
            "image": "postgres:16",
            "state": "exited",
            "status": "Exited (0) 2 days ago",
            "labels": {},
        },
        {
            "id": "ccc333",
            "names": ["/arcane"],
            "image": "ghcr.io/getarcaneapp/arcane:latest",
            "state": "running",
            "status": "Up 5 days",
            "labels": {},
            "redeployDisabled": True,
            "resourceSample": {"cpuPercent": 0.5, "memoryUsageBytes": 104857600, "memoryLimitBytes": 8589934592},
        },
    ],
    "counts": {"runningContainers": 2, "stoppedContainers": 1, "totalContainers": 3},
    "pagination": {"totalItems": 3, "totalPages": 1, "currentPage": 1, "itemsPerPage": 100},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def containers() -> dict[str, Any]:
    return copy.deepcopy(CONTAINERS)


@pytest.fixture
def arcane(aioclient_mock: AiohttpClientMocker, containers) -> AiohttpClientMocker:
    aioclient_mock.get(f"{API}/environments", json=ENVIRONMENTS)
    aioclient_mock.get(f"{API}/environments/0/containers", json=containers)
    aioclient_mock.get(f"{API}/environments/abc/containers", status=502, json={"detail": "agent unreachable"})
    for cid in ("aaa111", "bbb222", "ccc333"):
        for action in ("start", "stop", "restart", "redeploy"):
            aioclient_mock.post(f"{API}/environments/0/containers/{cid}/{action}", json={"success": True})
    return aioclient_mock


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Arcane",
        unique_id=URL.lower(),
        data={CONF_URL: URL, CONF_API_KEY: "arc_test", CONF_VERIFY_SSL: True},
    )
