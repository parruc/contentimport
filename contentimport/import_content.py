import base64
import re
import logging
import json
import os
import transaction

from App.config import getConfiguration
from collective.exportimport.import_content import ImportContent
from plone.namedfile.file import NamedBlobFile, NamedBlobImage
from plone import api

from unibo.magazine.content.articolo import IArticolo
from unibo.tiles.utils import TilesFactory


logger = logging.getLogger(__name__)
ARTICLES_IDS_REGEXP = re.compile(r"(/magazine/)archivio/\d{4}")
COMUNICATI_IDS_REGEXP = re.compile(r"(/magazine/)comunicati-stampa/\d{4}")

# map old to new views
VIEW_MAPPING = {
    "atct_album_view": "album_view",
    "prettyPhoto_album_view": "album_view",
    "folder_full_view": "full_view",
    "folder_listing": "listing_view",
    "folder_summary_view": "summary_view",
    "folder_tabular_view": "tabular_view",
    "atct_topic_view": "listing_view",
    "articolo_view": "view",
    "fotoracconto_view": "view",
    "file_view": "view",

}

PORTAL_TYPE_MAPPING = {
    "Topic": "Collection",
}

REVIEW_STATE_MAPPING = {}

VERSIONED_TYPES = []

IMPORTED_TYPES = [
    "Articolo",
    "Comunicato stampa",
]

ALLOWED_TYPES = []

CUSTOMVIEWFIELDS_MAPPING = {
    "warnings": None,
}

CHANGE_FIELDS_VALIDATION = {IArticolo: {"dipartimenti": ["required"], "description": ["max_length", "required"], "image": ["required"]}}
ORIGINAL_VALIDATIONS = {}


class CustomImportContent(ImportContent):

    DROP_PATHS = []

    DROP_UIDS = []

    def disable_validation(self):
        for ct, fields_dict in CHANGE_FIELDS_VALIDATION.items():
            ORIGINAL_VALIDATIONS[ct] = {}
            for field_name, validations in fields_dict.items():
                if field_name not in ORIGINAL_VALIDATIONS[ct]:
                    field = ct[field_name]
                    ORIGINAL_VALIDATIONS[ct][field_name] = {}
                for validation in validations:
                    if validation == "required":
                        ORIGINAL_VALIDATIONS[ct][field_name][validation] = field.required
                        field.required = False
                    elif validation == "max_length":
                        ORIGINAL_VALIDATIONS[ct][field_name][validation] = field.max_length
                        field.max_length = None
    
    def reenable_validation(self):
        for ct, fields_dict in ORIGINAL_VALIDATIONS.items():
            for field_name, validations in fields_dict.items():
                field = ct[field_name]
                for validation in validations:
                    if validation == "required":
                        field.required = ORIGINAL_VALIDATIONS[ct][field_name][validation]
                    elif validation == "max_length":
                        field.max_length = ORIGINAL_VALIDATIONS[ct][field_name][validation]

    def start(self):
        self.tiles_factory = TilesFactory()
        self.disable_validation()
        self.items_without_parent = []
        portal_types = api.portal.get_tool("portal_types")
        for portal_type in VERSIONED_TYPES:
            fti = portal_types.get(portal_type)
            behaviors = list(fti.behaviors)
            if 'plone.versioning' in behaviors:
                logger.info(f"Disable versioning for {portal_type}")
                behaviors.remove('plone.versioning')
            fti.behaviors = behaviors

    def finish(self):
        # export content without parents
        if self.items_without_parent:
            data = json.dumps(self.items_without_parent, sort_keys=True, indent=4)
            number = len(self.items_without_parent)
            cfg = getConfiguration()
            filename = 'content_without_parent.json'
            filepath = os.path.join(cfg.clienthome, filename)
            with open(filepath, 'w') as f:
                f.write(data)
            msg = u"Saved {} items without parent to {}".format(number, filepath)
            logger.info(msg)
            api.portal.show_message(msg, self.request)

    def commit_hook(self, added, index):
        msg = u"Committing after {} created items...".format(len(added))
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()
        if self.items_without_parent:
            data = json.dumps(self.items_without_parent, sort_keys=True, indent=4)
            number = len(self.items_without_parent)
            cfg = getConfiguration()
            filename = f'content_without_parent_{index}.json'
            filepath = os.path.join(cfg.clienthome, filename)
            with open(filepath, 'w') as f:
                f.write(data)
            msg = u"Saved {} items without parent to {}".format(number, filepath)
            logger.info(msg)

    def global_dict_hook(self, item):

        if "/bozze/" in item["@id"]:
            # Skip items in the bozze folder
            return None

        # Adapt this to your site
        old_portal_id = "magazine"
        new_portal_id = "magazine"

        if old_portal_id != new_portal_id:
            # This is only relevant for items in the site-root.
            # Most items containers are usually looked up by the uuid of the old parent
            item["@id"] = item["@id"].replace(f"/{old_portal_id}/", f"/{new_portal_id}/", 1)
            item["parent"]["@id"] = item["parent"]["@id"].replace(f"/{old_portal_id}", f"/{new_portal_id}", 1)

        # update constraints
        if item.get("exportimport.constrains"):
            types_fixed = []
            for portal_type in item["exportimport.constrains"]["locally_allowed_types"]:
                if portal_type in PORTAL_TYPE_MAPPING:
                    types_fixed.append(PORTAL_TYPE_MAPPING[portal_type])
                elif portal_type in ALLOWED_TYPES:
                    types_fixed.append(portal_type)
            item["exportimport.constrains"]["locally_allowed_types"] = list(set(types_fixed))

            types_fixed = []
            for portal_type in item["exportimport.constrains"]["immediately_addable_types"]:
                if portal_type in PORTAL_TYPE_MAPPING:
                    types_fixed.append(PORTAL_TYPE_MAPPING[portal_type])
                elif portal_type in ALLOWED_TYPES:
                    types_fixed.append(portal_type)
            item["exportimport.constrains"]["immediately_addable_types"] = list(set(types_fixed))

        # Layouts...
        if item.get("layout") in VIEW_MAPPING:
            new_view = VIEW_MAPPING[item["layout"]]
            if new_view:
                item["layout"] = new_view
            else:
                # drop unsupported views
                item.pop("layout")

        # Workflows...
        if item.get("review_state") in REVIEW_STATE_MAPPING:
            item["review_state"] = REVIEW_STATE_MAPPING[item["review_state"]]

        # Expires before effective
        effective = item.get('effective', None)
        expires = item.get('expires', None)
        if effective and expires and expires <= effective:
            item.pop('expires')

        # drop empty creator
        item["creators"] = [i for i in item.get("creators", []) if i]
        return item

    def dict_hook_articolo(self, item):
        # Change path for articles and subobjects
        item["@id"] = ARTICLES_IDS_REGEXP.sub(r"\1it/articoli", item["@id"])
        item["parent"]["@id"] = ARTICLES_IDS_REGEXP.sub(r"\1it/articoli", item["parent"]["@id"])
        return item

    def dict_hook_comunicatostampa(self, item):
        # Change path for press releases and subobjects
        item["@id"] = COMUNICATI_IDS_REGEXP.sub(r"\1it/comunicati-stampa", item["@id"])
        item["parent"]["@id"] = COMUNICATI_IDS_REGEXP.sub(r"\1it/comunicati-stampa", item["parent"]["@id"])
        return item

    def obj_hook_articolo(self, obj, item):
        tiles = item.pop("tiles", [])
        article_tiles = []
        # "tiles": [
        #         {
        #             "id": "sultan-qaboss-university", 
        #             "link": "http://www.squ.edu.om/", 
        #             "old_type": "inrete", 
        #             "title": "Sultan Qaboss University"
        #         }
        #     ],

        link_file_attachments_tile = {"title": "Allegati", "subobjects": []}
        fotogallery_tile = {"title": "Galleria fotografica", "subobjects": []}
        for tile in tiles:
            if tile["old_type"] in ["Link", "inrete"]:
                link_file_attachments_tile["subobjects"].append({"obj_type": "unibo.magazine.tiles.link.ILinkTile", "title": tile["title"], "url": tile["link"]})
            elif tile["old_type"] == "File":
                file_data = base64.b64decode(tile["file"])
                blob_file_obj = NamedBlobFile(
                    data=file_data,
                    filename=tile["filename"],
                    contentType=tile["content_type"]
                )
                link_file_attachments_tile["subobjects"].append({"obj_type": "unibo.magazine.tiles.allegato.IAllegatoTile", "title": tile["title"], "file": blob_file_obj})
            elif tile["old_type"] == "Image":
                image_data = base64.b64decode(tile["image"])
                blob_image_obj = NamedBlobImage(
                    data=image_data,
                    filename=tile["filename"],
                    contentType=tile["content_type"]
                )
                fotogallery_tile["subobjects"].append({"obj_type": "unibo.magazine.tiles.image.ISingleImage", "title": tile["title"], "alt": tile["title"], "didascalia": tile["description"], "image": blob_image_obj})

        if link_file_attachments_tile["subobjects"]:
            self.tiles_factory.create_tile(obj, self.request, "unibo.magazine.linkallegati", "content_tiles", **link_file_attachments_tile) 
        if fotogallery_tile["subobjects"]:
            self.tiles_factory.create_tile(obj, self.request, "unibo.magazine.fotogallery", "content_tiles", **fotogallery_tile)

    def create_container(self, item):
        """Override create_container to never create parents"""
        # Indead of creating a folder we save all items where this happens in a new json-file
        self.items_without_parent.append(item)

    def dict_hook_folder(self, item):
        return item


def fix_collection_query(query):
    fixed_query = []

    indexes_to_fix = [
        u'portal_type',
        u'review_state',
        u'Creator',
        u'Subject'
    ]
    operator_mapping = {
        # old -> new
        u"plone.app.querystring.operation.selection.is":
            u"plone.app.querystring.operation.selection.any",
        u"plone.app.querystring.operation.string.is":
            u"plone.app.querystring.operation.selection.any",
    }

    for crit in query:
        if crit["i"] == "portal_type" and len(crit["v"]) > 30:
            # Criterion is all types
            continue

        if crit["o"].endswith("relativePath") and crit["v"] == "..":
            # relativePath no longer accepts ..
            crit["v"] = "..::1"

        if crit["i"] in indexes_to_fix:
            for old_operator, new_operator in operator_mapping.items():
                if crit["o"] == old_operator:
                    crit["o"] = new_operator

        if crit["i"] == "portal_type":
            # Some types may have changed their names
            fixed_types = []
            for portal_type in crit["v"]:
                fixed_type = PORTAL_TYPE_MAPPING.get(portal_type, portal_type)
                fixed_types.append(fixed_type)
            crit["v"] = list(set(fixed_types))

        if crit["i"] == "review_state":
            # Review states may have changed their names
            fixed_states = []
            for review_state in crit["v"]:
                fixed_state = REVIEW_STATE_MAPPING.get(review_state, review_state)
                fixed_states.append(fixed_state)
            crit["v"] = list(set(fixed_states))

        if crit["o"] == "plone.app.querystring.operation.string.currentUser":
            crit["v"] = ""

        fixed_query.append(crit)

    return fixed_query
