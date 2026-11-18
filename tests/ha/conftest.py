import sys

import pytest

pytest.importorskip("homeassistant")

# The eflib tests replace the integration package with an empty stand-in so that
# Home Assistant is never imported. These tests need the real one.
for _name in ("custom_components.ecoflow_d3mp", "custom_components"):
    _module = sys.modules.get(_name)
    if _module is not None and getattr(_module, "__file__", None) is None:
        del sys.modules[_name]
