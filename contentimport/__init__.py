# -*- coding: utf-8 -*-
import pkg_resources
from pkg_resources import get_distribution, DistributionNotFound

# Patch first
original_get_distribution = get_distribution

def fake_get_distribution(dist_name, *args, **kwargs):
    if dist_name == "Products.Archetypes":
        raise DistributionNotFound
    return original_get_distribution(dist_name, *args, **kwargs)

pkg_resources.get_distribution = fake_get_distribution

# Then import your module — the patched version will run
import collective.exportimport.serializer
import collective.exportimport.export_content
import collective.exportimport.export_other

assert(serializer.HAS_AT is False)
assert(export_content.HAS_AT is False)
assert(export_other.HAS_AT is False)