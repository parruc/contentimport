from logging import getLogger
from pathlib import Path

import transaction
from App.config import getConfiguration
from bs4 import BeautifulSoup
from collective.exportimport.fix_html import (fix_html_in_content_fields,
                                              fix_html_in_portlets)
from plone import api
from plone.app.multilingual.dx.interfaces import IDexterityTranslatable
from plone.base.interfaces import ILanguage
from Products.Five import BrowserView
from zope.interface import alsoProvides

from contentimport.interfaces import IContentimportLayer

logger = getLogger(__name__)


class ImportAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()
        alsoProvides(request, IContentimportLayer)

        transaction.commit()
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import"

        # import content
        view = api.content.get_view("import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        request.form["handle_existing_content"] = 2  # 0 skip 1 replace 2 update
        view(server_file="bigea.json", return_json=True)
        transaction.commit()

        # collective.exportimport uses _createObjectByType which bypasses the
        # IObjectAddedEvent subscriber that normally stamps IDexterityTranslatable.
        # Without this marker ITranslationManager cannot adapt any content object,
        # so import_translations silently does nothing and the language switch
        # falls back to the site root.

        # self._fix_translatable_marker(portal)
        self._fix_content_languages(portal)
        transaction.commit()

        other_imports = [
            "relations",
            "members",
            "translations",
            "localroles",
            "ordering",
            "defaultpages",
            "redirects",
        ]
        for name in other_imports:
            view = api.content.get_view(f"import_{name}", portal, request)
            path = Path(directory) / f"export_{name}.json"
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.commit()
            else:
                logger.info(f"Missing file: {path}")

        fixers = [table_class_fixer, img_variant_fixer]
        results = fix_html_in_content_fields(fixers=fixers)
        msg = "Fixed html for {} content items".format(results)
        logger.info(msg)
        transaction.commit()

        results = fix_html_in_portlets()
        msg = "Fixed html for {} portlets".format(results)
        logger.info(msg)
        transaction.commit()

        reset_dates = api.content.get_view("reset_dates", portal, request)
        reset_dates()
        transaction.commit()

        reset_last_modified_by = api.content.get_view("reset_last_modified_by", portal, request)
        reset_last_modified_by()
        transaction.commit()

        return request.response.redirect(portal.absolute_url())

    def _fix_translatable_marker(self, portal):
        """Stamp IDexterityTranslatable on every object whose type declares
        the 'plone.translatable' behavior but is missing the marker (because
        collective.exportimport bypasses the normal creation pipeline)."""
        portal_types = api.portal.get_tool("portal_types")
        translatable_types = {
            name for name in portal_types.objectIds()
            if hasattr(portal_types[name], "behaviors")
            and "plone.translatable" in list(portal_types[name].behaviors)
        }
        catalog = api.portal.get_tool("portal_catalog")
        fixed = 0
        for brain in catalog.searchResults(
            path="/".join(portal.getPhysicalPath())
        ):
            if brain.portal_type not in translatable_types:
                continue
            try:
                obj = brain.getObject()
            except Exception:
                continue
            if not IDexterityTranslatable.providedBy(obj):
                alsoProvides(obj, IDexterityTranslatable)
                obj._p_changed = True
                fixed += 1
        logger.info("Stamped IDexterityTranslatable on %d objects", fixed)

    def _fix_content_languages(self, portal):
        """Set the language attribute on content imported inside LRFs.

        collective.exportimport bypasses PAM's createdEvent subscriber that
        normally sets obj.language based on the parent LRF.  Without this,
        brain.Language is always '' and @translations returns items: [].
        """
        catalog = api.portal.get_tool("portal_catalog")
        portal_path = "/".join(portal.getPhysicalPath())
        fixed = 0
        for lrf_brain in catalog.searchResults(
            portal_type="LRF",
            path=portal_path,
        ):
            lrf_lang = lrf_brain.getId
            if not lrf_lang:
                logger.warning(f"LRF {lrf_brain.getPath()} has no id, skipping")
                continue
            for brain in catalog.searchResults(
                Language="",
                path=lrf_brain.getPath(),
            ):
                try:
                    obj = brain.getObject()
                except Exception:
                    logger.warning(f"Could not get object for brain {brain.getPath()}, skipping")
                    continue
                ILanguage(obj).set_language(lrf_lang)
                obj.reindexObject(idxs=["Language"])
                fixed += 1
        logger.info("Fixed language attribute on %d objects", fixed)


def table_class_fixer(text, obj=None):
    if "table" not in text:
        return text
    dropped_classes = [
        "MsoNormalTable",
        "MsoTableGrid",
    ]
    replaced_classes = {
        "invisible": "invisible-grid",
    }
    soup = BeautifulSoup(text, "html.parser")
    for table in soup.find_all("table"):
        table_classes = table.get("class", [])
        for dropped in dropped_classes:
            if dropped in table_classes:
                table_classes.remove(dropped)
        for old, new in replaced_classes.items():
            if old in table_classes:
                table_classes.remove(old)
                table_classes.append(new)
        # all tables get the default bootstrap table class
        if "table" not in table_classes:
            table_classes.insert(0, "table")

    return soup.decode()


def img_variant_fixer(text, obj=None):
    """Set image-variants"""
    if not text:
        return text

    picture_variants = api.portal.get_registry_record("plone.picture_variants")
    scale_variant_mapping = {k: v["sourceset"][0]["scale"] for k, v in picture_variants.items()}
    scale_variant_mapping["thumb"] = "mini"
    fallback_variant = "preview"

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all("img"):
        if "data-val" not in tag.attrs:
            # maybe external image
            continue
        scale = tag["data-scale"]
        variant = scale_variant_mapping.get(scale, fallback_variant)
        tag["data-picturevariant"] = variant

        classes = tag["class"]
        new_class = f"picture-variant-{variant}"
        if new_class not in classes:
            classes.append(new_class)
            tag["class"] = classes

    return soup.decode()
