from ..models import Institutions, Collections, InstitutionsNormalized, CollectionsNormalized
from django.conf import settings
from django.db.models import Max
from django.db.models.functions import Cast, Coalesce
from django.db.models import Q
from datetime import datetime
from .es_mapping.es_mapping_cetaf_institutions import ESMappingCetafInstitutions
#install version 7 of es
from elasticsearch import Elasticsearch
import json
import re
import traceback

class ESLoader():

    es_client=None
    es_url=""
    es_institutions=""
    es_collections=""

    def __init__(self):        
        self.es_url=settings.ES_URL
        self.es_institutions=settings.ES_INDEX_INSTITUTIONS
        self.es_collections=settings.ES_INDEX_COLLECTIONS
        self.es_client=Elasticsearch(self.es_url)
        self._ensure_index_settings(self.es_institutions)
        self._ensure_index_settings(self.es_collections)
        
    def delete_all_institutions(self):
        self.es_client.delete_by_query(index=self.es_institutions, body={"query": {"match_all": {}}})
        
    def load_current_institutions(self):
        q=Institutions.objects.filter(current=True)        
        for inst in q:
            print(inst.uuid_institution_normalized)
            #print(inst.uuid_institution_normalized)
            #print(inst.data)
            data=inst.data
            #data["modification_date"]=inst.modification_date
            #data["version"]=inst.version
            options={}
            options["gs_collection_overview"]=settings.CETAF_DATA_ADDRESS["collection_overview"]
            flag_record, data=ESMappingCetafInstitutions.GetMapping(inst.uuid_institution_normalized, data, options)
            print("======================================>")
            if flag_record:
                print(data)
                resp = self.es_client.index(index=self.es_institutions, id=inst.uuid_institution_normalized, body=data)
                print(resp)
            
    def delete_all_collections(self):
        self.es_client.delete_by_query(index=self.es_collections, body={"query": {"match_all": {}}})
        
    def load_current_collections(self):
        q=Collections.objects.filter(current=True)        
        for coll in q:
            print(coll.uuid)
            print(coll.uuid_institution_normalized)
            print(coll.data)
            data=coll.data
            self._coerce_long_fields(data, {"declared_count_objects", "mids_1_%", "mids_2_%", "object_quantity"})
            self._coerce_float_fields(data, {"declared_count_type_specimens"})
            self._remove_empty_keys(data)
            self._remove_dot_keys(data)
            data["uuid_institution_normalized"]=coll.uuid_institution_normalized
            data["modification_date"]=coll.modification_date
            data["version"]=coll.version
            try:
                resp = self.es_client.index(index=self.es_collections, id=coll.uuid_collection_normalized, body=data)
                print(resp)
            except Exception as e:
                self._log_index_error(self.es_collections, coll.uuid_collection_normalized, data, e)
                exit(1)

# Ensure index settings and long / float mappings
    def _coerce_long_fields(self, obj, field_names):
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key in field_names:
                    parsed = self._parse_long(value)
                    if parsed is None:
                        del obj[key]
                    else:
                        obj[key] = parsed
                else:
                    self._coerce_long_fields(value, field_names)
        elif isinstance(obj, list):
            for item in obj:
                self._coerce_long_fields(item, field_names)

    def _parse_long(self, value):
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            digits = re.findall(r"\d+", value)
            if not digits:
                return None
            return int("".join(digits))
        return None

    def _coerce_float_fields(self, obj, field_names):
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key in field_names:
                    parsed = self._parse_float(value)
                    if parsed is None:
                        del obj[key]
                    else:
                        obj[key] = parsed
                else:
                    self._coerce_float_fields(value, field_names)
        elif isinstance(obj, list):
            for item in obj:
                self._coerce_float_fields(item, field_names)

    def _parse_float(self, value):
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            digits = re.findall(r"\d+", value)
            if not digits:
                return None
            return float("".join(digits))
        return None

    def _ensure_index_settings(self, index_name, total_fields_limit=10000):
        try:
            if not self.es_client.indices.exists(index=index_name):
                self.es_client.indices.create(
                    index=index_name,
                    body={"settings": {"index.mapping.total_fields.limit": total_fields_limit}},
                )
            else:
                self.es_client.indices.put_settings(
                    index=index_name,
                    body={"index.mapping.total_fields.limit": total_fields_limit},
                )
        except Exception:
            print(f"Warning: unable to update index settings for {index_name}")

    def _log_index_error(self, index_name, doc_id, data, exc, max_chars=2000):
        print(f"=====================ES index error on index={index_name} id={doc_id}: {exc}")
        if hasattr(exc, "info"):
            try:
                info = exc.info
                print(f"ES index error info: {json.dumps(info, default=str)[:max_chars]}")
                root = info.get("error", {}).get("root_cause", [])
                if root:
                    print(f"ES index error root_cause: {json.dumps(root, default=str)[:max_chars]}")
            except Exception as info_exc:
                print(f"ES index error: failed to serialize exc.info: {info_exc}")
        try:
            payload = json.dumps(data, default=str)
        except Exception as dump_exc:
            print(f"ES index error: failed to serialize payload: {dump_exc}")
            return
        if len(payload) > max_chars:
            payload = payload[:max_chars] + "...(truncated)"
        print(f"ES index error payload: {payload}")

    def _remove_empty_keys(self, obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                if not str(key).strip():
                    del obj[key]
                else:
                    self._remove_empty_keys(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                self._remove_empty_keys(item)

    def _remove_dot_keys(self, obj):
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                key_str = str(key)
                if "." in key_str or key_str.startswith(".") or key_str.endswith("."):
                    del obj[key]
                else:
                    self._remove_dot_keys(obj[key])
        elif isinstance(obj, list):
            for item in obj:
                self._remove_dot_keys(item)
