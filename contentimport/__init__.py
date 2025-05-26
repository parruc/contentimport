from unittest import mock
import importlib

with mock.patch("pkg_resources.get_distribution", side_effect=Exception("DistributionNotFound")):
    # Import the modules
    import collective.exportimport.serializer as serializer
    import collective.exportimport.export_content as export_content
    import collective.exportimport.export_other as export_other

    # Reload to apply the patched get_distribution
    importlib.reload(serializer)
    importlib.reload(export_content)
    importlib.reload(export_other)

    # Assertions
    assert serializer.HAS_AT is False
    assert export_content.HAS_AT is False
    assert export_other.HAS_AT is False