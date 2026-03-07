import json

from plone.dexterity.interfaces import IDexterityContent
from plone.restapi.deserializer.dxfields import DefaultFieldDeserializer
from plone.restapi.interfaces import IFieldDeserializer
from unibo.z3cform.fields.summary.field import (AutomaticSummary,
                                                IAutomaticSummaryField)
from zope.component import adapter
from zope.interface import implementer
from zope.publisher.interfaces.browser import IBrowserRequest


@implementer(IFieldDeserializer)
@adapter(IAutomaticSummaryField, IDexterityContent, IBrowserRequest)
class AutomaticSummaryFieldDeserializer(DefaultFieldDeserializer):

    def __call__(self, value):
        if value is None:
            return None
        # value comes as a dict {"items": ...} from the export
        if isinstance(value, dict):
            items = value.get("items")
            if items is None:
                return AutomaticSummary(items=None)
            if isinstance(items, (list, dict)):
                items = json.dumps(items)
            return AutomaticSummary(items=items)
        # fallback: if it's already a string, wrap it directly
        if isinstance(value, str):
            return AutomaticSummary(items=value)
        return AutomaticSummary(items=None)
