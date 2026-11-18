"""Pytest configuration for testing eflib without Home Assistant dependencies."""

import sys
from pathlib import Path
from types import ModuleType

# Create minimal stub modules for custom_components and ecoflow_d3mp - This prevents their
# __init__.py files from being executed
custom_components = ModuleType("custom_components")
custom_components.__path__ = []
sys.modules["custom_components"] = custom_components

ecoflow_d3mp = ModuleType("custom_components.ecoflow_d3mp")
ecoflow_d3mp.__path__ = [
    str(Path(__file__).parents[2] / "custom_components" / "ecoflow_d3mp")
]
sys.modules["custom_components.ecoflow_d3mp"] = ecoflow_d3mp

setattr(custom_components, "ecoflow_d3mp", ecoflow_d3mp)
