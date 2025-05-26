# -*- coding: utf-8 -*-
import sys
from unittest import mock
import pkg_resources

# Patch get_distribution to simulate missing "Products.Archetypes"
with mock.patch("pkg_resources.get_distribution", side_effect=pkg_resources.DistributionNotFound):
    
    # List of modules to reload
    modules_to_reload = [
        "collective.exportimport.serializer",
        "collective.exportimport.export_content",
        "collective.exportimport.export_other",
    ]

    # Unload them from sys.modules if already loaded
    for modname in modules_to_reload:
        if modname in sys.modules:
            del sys.modules[modname]

    # Now import them — this will evaluate HAS_AT under the patched environment
    import collective.exportimport.serializer as serializer
    import collective.exportimport.export_content as export_content
    import collective.exportimport.export_other as export_other

    # Assert that HAS_AT is correctly set to False in each module
    assert serializer.HAS_AT is False
    assert export_content.HAS_AT is False
    assert export_other.HAS_AT is False

    print("All HAS_AT flags are False — patch successful.")