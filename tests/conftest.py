"""Shared fixtures: an app on a temporary database and its test client."""

import pytest

from app import create_app
from app.config import TestConfig


@pytest.fixture
def app(tmp_path):
    class AppConfig(TestConfig):
        DATABASE_PATH = tmp_path / "monitor.db"
        SECRET_KEY = "test-secret-key"

    return create_app(AppConfig)


@pytest.fixture
def client(app):
    return app.test_client()
