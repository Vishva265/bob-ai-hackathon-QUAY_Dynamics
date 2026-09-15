"""Tests never implicitly load the workspace's active production/demo models."""
import pytest


@pytest.fixture(autouse=True)
def isolated_model_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('MODEL_DIRECTORY', str(tmp_path/'models'))
