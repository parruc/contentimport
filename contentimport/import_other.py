from logging import getLogger

from plone import api
from Products.Five import BrowserView

logger = getLogger(__name__)


class ResetLastModifiedBy(BrowserView):
    def __call__(self):
        self.title = "Reset last modified by"
        self.help_text = ("<p>Last modified by is changed by subscribers during import."
                          " This resets them to the original values of the imported content.</p>")
        if not self.request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()

        portal.ZopeFindAndApply(portal, search_sub=True, apply_func=reset_modifier)
        msg = "Finished resetting last modified by."
        logger.info(msg)
        api.portal.show_message(msg, self.request)
        return self.index()


def reset_modifier(obj, path):
    last_modifier = getattr(obj.aq_base, "last_modifier_migrated", None)
    if last_modifier and last_modifier != obj.last_modified_by:
        obj.last_modified_by = last_modifier
        del obj.last_modified_by
        obj.reindexObject(idxs=["last_modified_by"])
