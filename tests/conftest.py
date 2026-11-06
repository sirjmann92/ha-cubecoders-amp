"""Shared fixtures for the Cubecoders AMP tests."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):  # noqa: ARG001
    """Allow Home Assistant to load the integration from custom_components."""
    return
