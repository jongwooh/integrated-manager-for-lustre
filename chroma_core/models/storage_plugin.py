# Copyright (c) 2018 DDN. All rights reserved.
# Use of this source code is governed by a MIT-style
# license that can be found in the LICENSE file.

from collections import defaultdict
import json
import logging

from django.db import models
from django.db.models import Q, CASCADE

from chroma_core.models import AlertEvent
from chroma_core.models import AlertStateBase
from chroma_core.models import Volume
from chroma_core.models import ManagedTargetMount
from chroma_core.lib.storage_plugin.log import storage_plugin_log as log
from chroma_core.models.sparse_model import VariantDescriptor


# Our limit on the length of python names where we put
# them in CharFields -- python doesn't impose a limit, so this
# is pretty arbitrary
MAX_NAME_LENGTH = 128


class StoragePluginRecord(models.Model):
    """Reference to a module defining a BaseStoragePlugin subclass"""

    module_name = models.CharField(max_length=MAX_NAME_LENGTH)
    internal = models.BooleanField(default=False)

    class Meta:
        unique_together = ("module_name",)
        app_label = "chroma_core"
        ordering = ["id"]


class StorageResourceClass(models.Model):
    """Reference to a BaseStorageResource subclass"""

    storage_plugin = models.ForeignKey(StoragePluginRecord, on_delete=models.PROTECT)
    class_name = models.CharField(max_length=MAX_NAME_LENGTH)
    user_creatable = models.BooleanField(default=False)

    def __str__(self):
        return "%s/%s" % (self.storage_plugin.module_name, self.class_name)

    def get_class(self):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        return storage_plugin_manager.get_resource_class_by_id(self.pk)

    class Meta:
        unique_together = ("storage_plugin", "class_name")
        app_label = "chroma_core"
        ordering = ["id"]


class StorageResourceRecord(models.Model):
    """Reference to an instance of a BaseStorageResource"""

    resource_class = models.ForeignKey(StorageResourceClass, on_delete=models.PROTECT)

    # Representing a chroma_core.lib.storage_plugin.GlobalId or LocalId
    # TODO: put some checking for id_strs longer than this field: they
    # are considered 'unreasonable' and plugin authors should be
    # conservative in what they use for an ID
    storage_id_str = models.CharField(max_length=256)
    storage_id_scope = models.ForeignKey("StorageResourceRecord", blank=True, null=True, on_delete=models.PROTECT)

    # FIXME: when the id_scope is nullable a unique_together across it
    # doesn't enforce uniqueness for GlobalID resources

    # Parent-child relationships between resources
    parents = models.ManyToManyField("StorageResourceRecord", related_name="resource_parent")

    alias = models.CharField(max_length=64, blank=True, null=True)

    reported_by = models.ManyToManyField("StorageResourceRecord", related_name="resource_reported_by")

    class Meta:
        app_label = "chroma_core"
        unique_together = ("storage_id_str", "storage_id_scope", "resource_class")
        ordering = ["id"]

    def __str__(self):
        return self.alias_or_name()

    @classmethod
    def get_or_create_root(cls, resource_class, resource_class_id, attrs):
        # Root resource do not have parents so they must be globally identified
        from chroma_core.lib.storage_plugin.api.identifiers import AutoId, ScopedId

        if isinstance(resource_class._meta.identifier, ScopedId):
            raise RuntimeError("Cannot create root resource of class %s, it requires a scope" % resource_class)

        if isinstance(resource_class._meta.identifier, AutoId):
            import uuid

            attrs["chroma_auto_id"] = uuid.uuid4().__str__()
        id_str = json.dumps(resource_class.attrs_to_id_tuple(attrs, False))

        # NB assumes that none of the items in ID tuple are ResourceReferences: this
        # would raise an exception from json encoding.
        # FIXME: weird separate code path for creating resources (cf resourcemanager)
        try:
            # See if you're trying to create something which already exists
            existing_record = StorageResourceRecord.objects.get(
                resource_class=resource_class_id, storage_id_str=id_str, storage_id_scope=None
            )
            return existing_record, False
        except StorageResourceRecord.DoesNotExist:
            # Great, nothing in the way
            pass

        record = StorageResourceRecord(resource_class_id=resource_class_id, storage_id_str=id_str)
        record.save()

        log.info("StorageResourceRecord created %d" % (record.id))

        for name, value in attrs.items():
            attr_model_class = resource_class.attr_model_class(name)
            attr_model_class.objects.create(resource=record, key=name, value=attr_model_class.encode(value))

        return record, True

    def update_attributes(self, attributes):
        for key, val in attributes.items():
            self.update_attribute(key, val)

    def update_attribute(self, key, val):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        resource_class = storage_plugin_manager.get_resource_class_by_id(self.resource_class_id)

        # Try to update an existing record
        attr_model_class = resource_class.attr_model_class(key)
        updated = attr_model_class.objects.filter(resource=self, key=key).update(value=attr_model_class.encode(val))
        # If there was no existing record, create one
        if updated == 0:
            from django.db import IntegrityError

            try:
                attr_model_class.objects.create(resource=self, key=key, value=attr_model_class.encode(val))
            except IntegrityError:
                # Collided with another update, order undefined so let him win
                pass

    def delete_attribute(self, attr_name):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        resource_class = storage_plugin_manager.get_resource_class_by_id(self.resource_class_id)
        model_class = resource_class.attr_model_class(attr_name)
        try:
            model_class.objects.get(resource=self, key=attr_name).delete()
        except model_class.DoesNotExist:
            pass

    def items(self):
        for i in self.storageresourceattribute_set.all():
            yield (i.key, i.value)

    def to_resource(self):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        klass = storage_plugin_manager.get_resource_class_by_id(self.resource_class_id)
        attr_model_to_keys = defaultdict(list)
        for attr, attr_props in klass._meta.storage_attributes.items():
            attr_model_to_keys[attr_props.model_class].append(attr)
        storage_dict = {}
        for attr_model, keys in attr_model_to_keys.items():
            for attr in attr_model.objects.filter(resource=self, key__in=keys):
                storage_dict[attr.key] = attr_model.decode(attr.value)

        resource = klass(**storage_dict)
        resource._handle = self.id
        resource._handle_global = True
        return resource

    def alias_or_name(self, resource=None):
        if self.alias:
            return self.alias
        else:
            if not resource:
                resource = self.to_resource()
            return resource.get_label()

    def to_resource_class(self):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        klass, klass_id = storage_plugin_manager.get_plugin_resource_class(
            self.resource_class.storage_plugin.module_name, self.resource_class.class_name
        )
        return klass

    def get_statistic_properties(self, stat_name):
        from chroma_core.lib.storage_plugin.manager import storage_plugin_manager

        klass, klass_id = storage_plugin_manager.get_plugin_resource_class(
            self.resource_class.storage_plugin.module_name, self.resource_class.class_name
        )

        return klass._meta.storage_statistics[stat_name]


class SimpleHistoStoreBin(models.Model):
    histo_store_time = models.ForeignKey("SimpleHistoStoreTime", on_delete=CASCADE)
    bin_idx = models.IntegerField()
    value = models.PositiveIntegerField()

    class Meta:
        app_label = "chroma_core"
        ordering = ["id"]


class SimpleHistoStoreTime(models.Model):
    storage_resource_statistic = models.ForeignKey("StorageResourceStatistic", on_delete=CASCADE)
    time = models.PositiveIntegerField()

    class Meta:
        app_label = "chroma_core"
        ordering = ["id"]


class StorageResourceStatistic(models.Model):
    class Meta:
        unique_together = ("storage_resource", "name")
        app_label = "chroma_core"
        ordering = ["id"]

    storage_resource = models.ForeignKey(StorageResourceRecord, on_delete=models.PROTECT)
    sample_period = models.IntegerField()
    name = models.CharField(max_length=64)

    @property
    def metrics(self):
        from chroma_core.lib.metrics import VendorMetricStore

        if not hasattr(self, "_metrics"):
            self._metrics = VendorMetricStore(self)
        return self._metrics

    def update(self, stat_name, stat_properties, stat_data):
        from chroma_core.lib.storage_plugin.api import statistics

        if isinstance(stat_properties, statistics.BytesHistogram):
            # Histograms
            for dp in stat_data:
                ts = dp["timestamp"]
                bin_vals = dp["value"]
                from django.db import transaction

                with transaction.atomic():
                    time = SimpleHistoStoreTime.objects.create(time=ts, storage_resource_statistic=self)
                    for i in range(0, len(stat_properties.bins)):
                        SimpleHistoStoreBin.objects.create(bin_idx=i, value=bin_vals[i], histo_store_time=time)
                    # Only keep latest time
                    SimpleHistoStoreTime.objects.filter(~Q(id=time.id), storage_resource_statistic=self).delete()
            return []
        for i in stat_data:
            i["value"] = float(i["value"])
        return self.metrics.serialize(stat_name, stat_properties, stat_data)
