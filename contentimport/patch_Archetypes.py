# patch_archetypes.py

import sys
import pkg_resources
from pkg_resources import DistributionNotFound

def patch_has_at_false(event=None):
    """
    Patch pkg_resources.get_distribution so that 'Products.Archetypes' appears missing,
    then reload collective.exportimport modules so they set HAS_AT = False correctly.
    """

    original_get_distribution = pkg_resources.get_distribution

    def fake_get_distribution(dist_name, *args, **kwargs):
        if dist_name == "Products.Archetypes":
            raise DistributionNotFound()
        return original_get_distribution(dist_name, *args, **kwargs)

    pkg_resources.get_distribution = fake_get_distribution

    modules = [
        "collective.exportimport.serializer",
        "collective.exportimport.export_content",
        "collective.exportimport.export_other",
    ]

    for modname in modules:
        if modname in sys.modules:
            del sys.modules[modname]

    import collective.exportimport.serializer
    import collective.exportimport.export_content
    import collective.exportimport.export_other

    assert collective.exportimport.serializer.HAS_AT is False
    assert collective.exportimport.export_content.HAS_AT is False
    assert collective.exportimport.export_other.HAS_AT is False

    # Optional: restore original after patching to avoid side effects
    pkg_resources.get_distribution = original_get_distribution