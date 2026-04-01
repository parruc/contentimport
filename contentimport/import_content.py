import base64
import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime

import transaction
from App.config import getConfiguration
from collective.exportimport.import_content import ImportContent
from persistent.mapping import PersistentMapping
from plone import api
from plone.app.textfield.interfaces import IRichText, IRichTextValue
from plone.app.textfield.value import RichTextValue
from plone.dexterity.utils import resolveDottedName
from plone.formwidget.geolocation import Geolocation, GeolocationField
from plone.namedfile.file import NamedBlobFile, NamedBlobImage
from plone.namedfile.interfaces import INamedBlobImageField, INamedFileField
from plone.tiles.data import ANNOTATIONS_KEY_PREFIX
from plone.tiles.interfaces import ITileType
from unibo.tiles.browser.multiobject import TileObject
from zope.annotation.interfaces import IAnnotations
from zope.component import getUtilitiesFor
from zope.dottedname.resolve import resolve
from zope.interface import alsoProvides
from zope.schema import getFieldsInOrder
from zope.schema.interfaces import IDate, IDatetime

logger = logging.getLogger(__name__)
MARKER_INTERFACES_KEY = "exportimport.marker_interfaces"
TILES_KEY = "exportimport.tiles_data"

# Mapping of old subobject interface dotted names (unibo.tiles.multiobject.*)
# to the new locations in unibo.dipartimenti.tiles.*
SUBOBJECT_TYPE_MAPPING = {
    "unibo.tiles.multiobject.link.ILink":
        "unibo.dipartimenti.tiles.link.ILink",
    "unibo.tiles.multiobject.attachment.IAttachment":
        "unibo.dipartimenti.tiles.attachment.IAttachment",
    "unibo.tiles.multiobject.contatto.IContatto":
        "unibo.dipartimenti.tiles.contatto.IContatto",
    "unibo.tiles.multiobject.contatto.IContattoDSA":
        "unibo.dipartimenti.tiles.contatto.IContattoDSA",
    "unibo.tiles.multiobject.contatto.IStrutturaDSA":
        "unibo.dipartimenti.tiles.contatto.IStrutturaDSA",
    "unibo.tiles.multiobject.banners.IBanner":
        "unibo.dipartimenti.tiles.lancio_ambiti.IBanner",
    "unibo.tiles.multiobject.album.IFotoAlbum":
        "unibo.dipartimenti.tiles.album.IFotoAlbum",
    "unibo.tiles.multiobject.summary_links.ILink":
        "unibo.dipartimenti.tiles.summary_links.ILink",
    "unibo.tiles.multiobject.map_multipoint.IMapPosition":
        "unibo.dipartimenti.tiles.map_multipoint.IMapPosition",
    "unibo.tiles.multiobject.video.IVideo":
        "unibo.dipartimenti.tiles.media_gallery.IVideo",
    "unibo.tiles.multiobject.image.IImage":
        "unibo.dipartimenti.tiles.galleria.IImage",
}

# map old to new views
VIEW_MAPPING = {
    "atct_album_view": "album_view",
    "prettyPhoto_album_view": "album_view",
    "folder_full_view": "full_view",
    "folder_listing": "listing_view",
    "folder_summary_view": "summary_view",
    "folder_tabular_view": "tabular_view",
    "atct_topic_view": "listing_view",
}

PORTAL_TYPE_MAPPING = {
    "LanguageFolder": "LRF",
}

REVIEW_STATE_MAPPING = {}

VERSIONED_TYPES = []

IMPORTED_TYPES = [
    "Document",
    "Folder",
    "Link",
    "File",
    "Image",
    "News Item",
    "Event",
    "EasyForm",
    # Custom dipartimenti types
    "HomePage",
    "Banner",
    "Channel",
    "Newsletter",
    "CorsiStudio",
    "Events",
    "AgendaEventi",
    "AgendaEvento",
    "AltaFormazione",
    "Ambito",
    "Collane",
    "Contacts",
    "Dottorati",
    "GuidaOnline",
    "LanguageFolder",
    "LRF",
    "Masters",
    "MediaGallery",
    "NewsRoom",
    "OverviewInternazionale",
    "Personale",
    "Pubblicazioni",
    "Ricerca",
    "ScuoleSpecializzazione",
    "SiteContainer",
    "SommarioAmbiti",
    "StrilloEvento",
    "StrilloNotizia",
    "Visiting",
]

ALLOWED_TYPES = [
    "Collection",
    "Document",
    "Folder",
    "Link",
    "File",
    "Image",
    "News Item",
    "Event",
    "EasyForm",
    # Custom dipartimenti types
    "HomePage",
    "Banner",
    "Channel",
    "Newsletter",
    "CorsiStudio",
    "AgendaEventi",
    "AgendaEvento",
    "AltaFormazione",
    "Ambito",
    "Collane",
    "Contacts",
    "Dottorati",
    "GuidaOnline",
    "LanguageFolder",
    "LRF",
    "Masters",
    "MediaGallery",
    "NewsRoom",
    "OverviewInternazionale",
    "Personale",
    "Pubblicazioni",
    "Ricerca",
    "ScuoleSpecializzazione",
    "SiteContainer",
    "SommarioAmbiti",
    "StrilloEvento",
    "StrilloNotizia",
    "Visiting",
]

CUSTOMVIEWFIELDS_MAPPING = {
    "warnings": None,
}


class CustomImportContent(ImportContent):

    DROP_PATHS = []

    DROP_UIDS = []

    INCLUDE_PATHS = []

    def start(self):
        self.request.set('_collective_exportimport_importing', True)
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

        if item["@type"] in PORTAL_TYPE_MAPPING:
            item["@type"] = PORTAL_TYPE_MAPPING[item["@type"]]
        if "@parent" in item and item["@parent"]["@type"] in PORTAL_TYPE_MAPPING:
            item["@parent"]["@type"] = PORTAL_TYPE_MAPPING[item["@parent"]["@type"]]

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

        # drop empty creator
        item["creators"] = [i for i in item.get("creators", []) if i]

        return item

    def global_obj_hook_before_deserializing(self, obj, item):
        """Apply marker interfaces before deserializing."""
        for iface_name in item.pop(MARKER_INTERFACES_KEY, []):
            iface = resolveDottedName(iface_name)
            if not iface.providedBy(obj):
                alsoProvides(obj, iface)
                logger.info("Applied marker interface %s to %s", iface_name, obj.absolute_url())
        return obj, item

    def global_obj_hook(self, obj, item):
        """Import tiles annotation data after the object has been deserialized."""
        if item.get(TILES_KEY):
            self.import_tiles(obj, item)

        last_modifier = item.get("last_modifier", None)
        if last_modifier:
            obj.last_modifier_migrated = last_modifier
        return obj

    def import_tiles(self, obj, item):
        """Restore tile annotation data onto the content object."""

        tiles_data = item.pop(TILES_KEY, {})
        if not tiles_data:
            return

        annotations = IAnnotations(obj, None)
        if annotations is None:
            return

        # Build field-type sets per tile type name, once for all tiles
        richtext_fields = defaultdict(set)
        image_fields = defaultdict(set)
        file_fields = defaultdict(set)
        datetime_fields = defaultdict(set)
        date_fields = defaultdict(set)
        for tile_name, tile_type_util in getUtilitiesFor(ITileType):
            if not tile_type_util.schema:
                continue
            for fname, fld in getFieldsInOrder(tile_type_util.schema):
                if IRichText.providedBy(fld):
                    richtext_fields[tile_name].add(fname)
                elif INamedBlobImageField.providedBy(fld):
                    image_fields[tile_name].add(fname)
                elif INamedFileField.providedBy(fld):
                    file_fields[tile_name].add(fname)
                elif IDatetime.providedBy(fld):
                    datetime_fields[tile_name].add(fname)
                elif IDate.providedBy(fld):
                    date_fields[tile_name].add(fname)

        for tile_id, tile_data in tiles_data.items():
            tile_type_name = tile_data.pop("__tile_type__", None)
            annotation_key = "{}.{}".format(ANNOTATIONS_KEY_PREFIX, tile_id)

            restored = {}
            for key, value in tile_data.items():
                if key == "objects_dict":
                    restored[key] = self._import_objects_dict(value, obj)
                elif key in richtext_fields.get(tile_type_name, set()):
                    if value is not None and not IRichTextValue.providedBy(value):
                        restored[key] = RichTextValue(value, "text/html", "text/x-html-safe")
                    else:
                        restored[key] = value
                elif key in image_fields.get(tile_type_name, set()):
                    restored[key] = self._restore_blob(value, NamedBlobImage, tile_id)
                elif key in file_fields.get(tile_type_name, set()):
                    restored[key] = self._restore_blob(value, NamedBlobFile, tile_id)
                elif key in datetime_fields.get(tile_type_name, set()):
                    restored[key] = self._parse_datetime(value)
                elif key in date_fields.get(tile_type_name, set()):
                    restored[key] = self._parse_date(value)
                else:
                    restored[key] = value

            annotations[annotation_key] = PersistentMapping(restored)

    def _import_objects_dict(self, objects_data, obj):
        """Reconstruct a PersistentMapping of TileObject instances."""
        result = PersistentMapping()
        for uid, obj_data in (objects_data or {}).items():
            tileobj = TileObject()
            tileobj.obj_uid = uid  # uid == obj_uid is an invariant; set it first as a guarantee

            # Map old obj_type to the new dotted name
            old_obj_type = obj_data.get("obj_type", "") or ""
            new_obj_type = SUBOBJECT_TYPE_MAPPING.get(old_obj_type, old_obj_type)

            # Build field-type sets from the new subobject schema
            richtext_fields = set()
            image_fields = set()
            file_fields = set()
            geo_fields = set()
            datetime_fields = set()
            date_fields = set()
            if new_obj_type:
                try:
                    sub_schema = resolve(new_obj_type)
                    for fname, fld in getFieldsInOrder(sub_schema):
                        if IRichText.providedBy(fld):
                            richtext_fields.add(fname)
                        elif INamedBlobImageField.providedBy(fld):
                            image_fields.add(fname)
                        elif INamedFileField.providedBy(fld):
                            file_fields.add(fname)
                        elif GeolocationField is not None and isinstance(fld, GeolocationField):
                            geo_fields.add(fname)
                        elif IDatetime.providedBy(fld):
                            datetime_fields.add(fname)
                        elif IDate.providedBy(fld):
                            date_fields.add(fname)
                except Exception:
                    logger.exception("Could not resolve subobject schema %s", new_obj_type)

            for attr, value in obj_data.items():
                if attr == "obj_type":
                    setattr(tileobj, "obj_type", new_obj_type)
                elif attr in richtext_fields:
                    if value is not None and not IRichTextValue.providedBy(value):
                        setattr(tileobj, attr, RichTextValue(value, "text/html", "text/x-html-safe"))
                    else:
                        setattr(tileobj, attr, value)
                elif attr in image_fields:
                    setattr(tileobj, attr, self._restore_blob(value, NamedBlobImage, uid))
                elif attr in file_fields:
                    setattr(tileobj, attr, self._restore_blob(value, NamedBlobFile, uid))
                elif attr in geo_fields and Geolocation is not None:
                    if isinstance(value, dict):
                        setattr(tileobj, attr, Geolocation(value.get("latitude", 0), value.get("longitude", 0)))
                    else:
                        setattr(tileobj, attr, value)
                elif attr in datetime_fields:
                    setattr(tileobj, attr, self._parse_datetime(value))
                elif attr in date_fields:
                    setattr(tileobj, attr, self._parse_date(value))
                else:
                    setattr(tileobj, attr, value)

            result[uid] = tileobj
        return result

    def _parse_datetime(self, value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            logger.warning("Could not parse datetime value: %r", value)
            return None

    def _parse_date(self, value):
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            logger.warning("Could not parse date value: %r", value)
            return None

    def _restore_blob(self, data, klass, context_info=""):
        """Restore a NamedBlobImage or NamedBlobFile from base64-encoded export data."""
        if not data or not isinstance(data, dict):
            return None
        raw_b64 = data.get("data")
        if not raw_b64:
            logger.info("No blob data found for %s, skipping", context_info)
            return None
        try:
            blobdata = base64.b64decode(raw_b64)
        except Exception:
            logger.exception("Could not decode blob data for %s", context_info)
            return None
        filename = data.get("filename", "")
        content_type = data.get("content-type", "")
        return klass(
            data=blobdata,
            contentType=content_type,
            filename=filename,
        )

    def create_container(self, item):
        """Override create_container to never create parents"""
        # Indead of creating a folder we save all items where this happens in a new json-file
        self.items_without_parent.append(item)

    def dict_hook_folder(self, item):
        return item

    def dict_hook_event(self, item):
        # drop empty strings as event_url
        if item.get("event_url", None) == "":
            item.pop("event_url")
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
