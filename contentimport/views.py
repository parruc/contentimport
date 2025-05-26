from App.config import getConfiguration
from bs4 import BeautifulSoup
from collective.exportimport.fix_html import fix_html_in_content_fields
from collective.exportimport.fix_html import fix_html_in_portlets
from contentimport.interfaces import IContentimportLayer
from logging import getLogger
from pathlib import Path
from plone import api
from Products.Five import BrowserView
from zope.interface import alsoProvides

import transaction

logger = getLogger(__name__)

DEFAULT_ADDONS = []


class ImportAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()
        alsoProvides(request, IContentimportLayer)
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import"

        # import content
        view = api.content.get_view("import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        view(server_file="CUE.json", return_json=True)
        transaction.commit()

        other_imports = [
        ]

        for name in other_imports:
            view = api.content.get_view("import_{}".format(name), portal, request)
            path = Path(directory) / "export_{}.json".format(name)
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.commit()
            else:
                logger.info(u"Missing file: {}".format(path))

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

        return request.response.redirect(portal.absolute_url())


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
        new_class = u"picture-variant-{}".format(variant)
        if new_class not in classes:
            classes.append(new_class)
            tag["class"] = classes

    return soup.decode()
