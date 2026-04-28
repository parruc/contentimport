from logging import getLogger
from pathlib import Path

import requests
import transaction
from App.config import getConfiguration
from bs4 import BeautifulSoup
from collective.exportimport.fix_html import (fix_html_in_content_fields,
                                              fix_html_in_portlets)
from plone import api
from plone.base.utils import get_installer
from plone.volto.browser.migrate_to_volto import migrate_richtext_to_blocks
from plone.volto.setuphandlers import add_behavior, remove_behavior
from Products.CMFEditions.interfaces.IModifier import \
    FileTooLargeToVersionError
from Products.Five import BrowserView
from Products.ZCatalog.ProgressHandler import ZLogHandler
from zope.interface import alsoProvides

from contentimport.interfaces import IContentimportLayer

logger = getLogger(__name__)

# Add you own project-specific add-ons here
DEFAULT_ADDONS = []

VERSIONED_TYPES = [
    "Document",
    "News Item",
    "Event",
    "Link",
]


class ImportAll(BrowserView):
    def __call__(self):
        request = self.request
        # Check if Blocks-conversion-tool is running
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        r = requests.post(
            "http://localhost:5000/html", headers=headers, json={"html": "<p>text</p>"}
        )
        r.raise_for_status()

        # Submit a simple form template to trigger the import
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()
        alsoProvides(request, IContentimportLayer)

        installer = get_installer(portal)
        if not installer.is_product_installed("contentimport"):
            installer.install_product("contentimport")

        # install required add-ons
        for addon in DEFAULT_ADDONS:
            if not installer.is_product_installed(addon):
                installer.install_product(addon)

        # Disable versioning before import
        for portal_type in VERSIONED_TYPES:
            remove_behavior(portal_type, "plone.versioning")
            remove_behavior(portal_type, "plone.locking")

        # Fake the target being a classic site even though plone.volto is installed...
        # 1. Allow Folders and Collections (they are disabled in Volto by default)
        portal_types = api.portal.get_tool("portal_types")
        portal_types["Collection"].global_allow = True
        portal_types["Folder"].global_allow = True
        # 2. Enable richtext behavior (otherwise no text will be imported)
        for portal_type in ["Document", "News Item", "Event"]:
            add_behavior(portal_type, "plone.richtext")

        transaction.commit()
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import"

        # Import content
        view = api.content.get_view("import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        # Change "Plone.json" to the name of your export file
        view(server_file="Plone.json", return_json=True)
        transaction.commit()

        # Run all other imports
        other_imports = [
            "relations",
            "members",
            "translations",
            "localroles",
            "ordering",
            "defaultpages",
            "discussion",
            "portlets",  # not really useful in Volto
            "redirects",
        ]
        for name in other_imports:
            view = api.content.get_view(f"import_{name}", portal, request)
            path = Path(directory) / f"export_{name}.json"
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.get().note(f"Finished import_{name}")
                transaction.commit()
            else:
                logger.info(f"Missing file: {path}")

        # Optional: Run html-fixers on richtext
        fixers = [
            table_class_fixer,
            img_variant_fixer,
            scale_unscaled_images,
            fix_image_align,
        ]
        results = fix_html_in_content_fields(fixers=fixers)
        msg = "Fixed html for {} content items".format(results)
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        results = fix_html_in_portlets()
        msg = "Fixed html for {} portlets".format(results)
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        # Add blocks behavior to collections to convert richtext to blocks
        for portal_type in ["Collection"]:
            add_behavior(portal_type, "volto.blocks")

        # Update linksintegrity
        view = api.content.get_view("updateLinkIntegrityInformation", portal, request)
        results = view.update()
        msg = f"Updated linkintegrity for {results} items"
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        # Rebuilding the catalog is necessary to prevent issues later on
        catalog = api.portal.get_tool("portal_catalog")
        logger.info("Rebuilding catalog...")
        catalog.clearFindAndRebuild()
        msg = "Finished rebuilding catalog!"
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        # This uses the blocks-conversion-tool to migrate to blocks
        logger.info("Start migrating richtext to blocks...")
        migrate_richtext_to_blocks(purge_richtext=True)
        msg = "Finished migrating richtext to blocks"
        transaction.get().note(msg)
        transaction.commit()

        # Reuse the migration-form from plone.volto to do some more tasks
        view = api.content.get_view("migrate_to_volto", portal, request)
        # Yes, we want to migrate default pages
        view.migrate_default_pages = True
        view.slate = True
        view.purge_richtext = True
        view.service_url = "http://localhost:5000/html"
        logger.info("Start migrating Folders to Documents...")
        view.do_migrate_folders()
        msg = "Finished migrating Folders to Documents!"
        transaction.get().note(msg)
        transaction.commit()

        logger.info("Start migrating Collections to Documents...")
        view.migrate_collections()
        msg = "Finished migrating Collections to Documents!"
        transaction.get().note(msg)
        transaction.commit()

        reset_dates = api.content.get_view("reset_dates", portal, request)
        reset_dates()
        transaction.commit()

        # Reindex created and modified
        catalog = api.portal.get_tool("portal_catalog")
        pghandler = ZLogHandler(5000)
        catalog.reindexIndex(["created", "modified"], None, pghandler=pghandler)

        # re-enable versioning and add initial versions
        for portal_type in VERSIONED_TYPES:
            add_behavior(portal_type, "plone.versioning")
            add_behavior(portal_type, "plone.locking")
        logger.info("Creating initial versions")
        portal_repository = api.portal.get_tool("portal_repository")
        brains = api.content.find(portal_type=VERSIONED_TYPES, sort_on="path")
        total = len(brains)
        for index, brain in enumerate(brains):
            obj = brain.getObject()
            try:
                if not portal_repository.getHistoryMetadata(obj=obj):
                    portal_repository.save(obj=obj, comment="Imported Version")
            except FileTooLargeToVersionError:
                pass
            if not index % 1000:
                msg = f"Created versions for {index} of {total} items."
                logger.info(msg)
                transaction.get().note(msg)
                transaction.commit()
        msg = "Created initial versions"
        transaction.get().note(msg)
        transaction.commit()

        # Disallow folders and collections again
        portal_types["Collection"].global_allow = False
        portal_types["Folder"].global_allow = False

        # Disable richtext behavior again
        for type_ in ["Document", "News Item", "Event"]:
            remove_behavior(type_, "plone.richtext")

        # Remove contentimport to also drop the BrowserLayer
        if installer.is_product_installed("contentimport"):
            installer.uninstall_product("contentimport")

            logger.info("Finished import_all")
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
    scale_variant_mapping = {
        k: v["sourceset"][0]["scale"] for k, v in picture_variants.items()
    }
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


def scale_unscaled_images(text, obj=None):
    """Scale unscaled image"""
    if not text:
        return text
    fallback_scale = "huge"

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all("img"):
        if "data-val" not in tag.attrs:
            # maybe external image
            continue

        scale = tag["data-scale"]
        # Prevent unscaled images!
        if not scale:
            scale = fallback_scale
            tag["data-scale"] = fallback_scale
        if not tag["src"].endswith(scale):
            tag["src"] = tag["src"] + "/" + scale

    return soup.decode()


def fix_image_align(text, obj=None):
    """Replace align='xx' with css-classes"""
    if not text:
        return text

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all("img"):
        if "align" not in tag.attrs:
            continue

        classes = tag.get("class", [])
        direction = tag["align"]
        if direction == "left":
            classes.append("image-left")
        elif direction == "right":
            classes.append("image-right")
        if "image-inline" in classes:
            classes.remove("image-inline")
        del tag["align"]
    return soup.decode()
