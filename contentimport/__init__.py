# -*- coding: utf-8 -*-
import sys
import pkg_resources
from pkg_resources import get_distribution, DistributionNotFound

# Save the original function so we can restore it later
original_get_distribution = get_distribution

# Define the fake version
def fake_get_distribution(dist_name, *args, **kwargs):
    if dist_name == "Products.Archetypes":
        raise DistributionNotFound
    return original_get_distribution(dist_name, *args, **kwargs)

# Monkeypatch it
pkg_resources.get_distribution = fake_get_distribution

# List of modules to force re-import
modules_to_reload = [
    "collective.exportimport.serializer",
    "collective.exportimport.export_content",
    "collective.exportimport.export_other",
]

# Delete from sys.modules to force fresh import
for modname in modules_to_reload:
    if modname in sys.modules:
        del sys.modules[modname]

# Now import the modules (they'll re-evaluate HAS_AT using the patched function)
from collective.exportimport import serializer
from collective.exportimport import export_content
from collective.exportimport import export_other

# Run assertions
assert serializer.HAS_AT is False
assert export_content.HAS_AT is False
assert export_other.HAS_AT is False

print("All HAS_AT flags are False — patch successful.")

# (Optional) Restore original function if needed elsewhere
pkg_resources.get_distribution = original_get_distribution