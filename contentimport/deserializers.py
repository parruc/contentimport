import json

from plone.dexterity.interfaces import IDexterityContent
from plone.restapi.deserializer.dxfields import DefaultFieldDeserializer
from plone.restapi.interfaces import IFieldDeserializer
from unibo.dipartimenti.fields.automaticsummary import IAutomaticSummaryField
from zope.component import adapter
from zope.interface import implementer
from zope.publisher.interfaces.browser import IBrowserRequest


def _normalize_items(items):
    """Strip old-widget-only keys and keep only the fields the new field uses."""
    result = []
    for row in items:
        if not isinstance(row, dict):
            continue
        clean = {"id": row["id"], "hidden": row.get("hidden", False)}
        # Keep title/description overrides only when explicitly set
        if row.get("title") is not None:
            clean["title"] = row["title"]
        if row.get("description") is not None:
            clean["description"] = row["description"]
        result.append(clean)
    return result


@implementer(IFieldDeserializer)
@adapter(IAutomaticSummaryField, IDexterityContent, IBrowserRequest)
class AutomaticSummaryFieldDeserializer(DefaultFieldDeserializer):

    def __call__(self, value):
        if value is None:
            return None
        # Old export format: {"items": [...]}
        if isinstance(value, dict):
            items = value.get("items")
            if not items:
                return None
            return json.dumps(_normalize_items(items))
        # Already a JSON string
        if isinstance(value, str):
            return value
        return None
