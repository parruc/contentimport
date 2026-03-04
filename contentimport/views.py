from App.config import getConfiguration
from bs4 import BeautifulSoup
from collective.exportimport.fix_html import fix_html_in_content_fields
from collective.exportimport.fix_html import fix_html_in_portlets
from contentimport.interfaces import IContentimportLayer
from json import dumps
from json import loads
from logging import getLogger
from pathlib import Path
from plone import api
from Products.CMFPlone.utils import get_installer
from Products.Five import BrowserView
from zope.interface import alsoProvides

import transaction

logger = getLogger(__name__)

DEFAULT_ADDONS = []
IMPORT_FILENAMES = [
    "scienzaa2voci.json",
    "Plone.json",
]

LEGACY_LAYOUT_MAPPING = {
    "atct_album_view": "album_view",
    "prettyPhoto_album_view": "album_view",
    "folder_full_view": "full_view",
    "folder_listing": "listing_view",
    "folder_summary_view": "summary_view",
    "folder_tabular_view": "tabular_view",
    "atct_topic_view": "listing_view",
}

DEFAULT_LAYOUT_BY_TYPE = {
    "Biography": "biography_view",
    "Biography_container": "search_view",
    "HomePage": "homepage",
}


def pick_import_file(directory):
    for filename in IMPORT_FILENAMES:
        path = Path(directory) / filename
        if path.exists():
            return filename
    return "Plone.json"


def normalize_uid_list(values):
    if not values:
        return []
    normalized = []
    if isinstance(values, str):
        values = [values]
    for value in values:
        if isinstance(value, str):
            normalized.append(value)
            continue
        if not isinstance(value, dict):
            continue
        for key in ("UID", "uid", "token", "uuid"):
            uid = value.get(key)
            if uid:
                normalized.append(uid)
                break
    return normalized


def normalize_person_relations(value):
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        value = [value]
    normalized = []
    for relation in value:
        if not isinstance(relation, dict):
            continue
        relation_type = relation.get("relationsType") or relation.get("relationType") or ""
        related = relation.get("relatedBiography") or relation.get("related") or relation.get("uid") or ""
        normalized.append(
            dumps(
                {
                    "relationsType": relation_type,
                    "relatedBiography": related,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return normalized


def apply_scienzaa2voci_import_fixes(portal):
    changed = 0
    brains = api.content.find(
        portal_type=["Biography", "Biography_container", "HomePage"],
    )
    for brain in brains:
        obj = brain.getObject()
        dirty = False

        layout = getattr(obj, "layout", None)
        if layout in LEGACY_LAYOUT_MAPPING:
            obj.layout = LEGACY_LAYOUT_MAPPING[layout]
            dirty = True
        elif not layout:
            default_layout = DEFAULT_LAYOUT_BY_TYPE.get(brain.portal_type)
            if default_layout:
                obj.layout = default_layout
                dirty = True

        if brain.portal_type == "HomePage":
            current = getattr(obj, "biographies", None)
            fixed = normalize_uid_list(current)
            if current != fixed:
                setattr(obj, "biographies", fixed)
                dirty = True

        if brain.portal_type == "Biography":
            current = getattr(obj, "personRelations", None)
            fixed = normalize_person_relations(current)
            if current != fixed:
                setattr(obj, "personRelations", fixed)
                dirty = True

        if dirty:
            obj.reindexObject()
            changed += 1
    return changed


class ImportAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()
        alsoProvides(request, IContentimportLayer)

        installer = get_installer(portal)
        if not installer.is_product_installed("contentimport"):
            installer.install_product("contentimport")

        # install required addons
        for addon in DEFAULT_ADDONS:
            if not installer.is_product_installed(addon):
                installer.install_product(addon)

        transaction.commit()
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import"

        # import content
        view = api.content.get_view("import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        import_file = pick_import_file(directory)
        logger.info(f"Using import file: {import_file}")
        view(server_file=import_file, return_json=True)
        transaction.commit()

        other_imports = [
            "relations",
            "members",
            "translations",
            "localroles",
            "ordering",
            "defaultpages",
            "discussion",
            "portlets",
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

        changed = apply_scienzaa2voci_import_fixes(portal)
        msg = f"Applied scienzaa2voci post-import fixes to {changed} items"
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
        new_class = f"picture-variant-{variant}"
        if new_class not in classes:
            classes.append(new_class)
            tag["class"] = classes

    return soup.decode()
