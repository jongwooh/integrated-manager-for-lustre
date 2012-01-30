
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

from django.db import models
from django.contrib.contenttypes.models import ContentType

from monitor.models import Event, AlertState, AlertEvent

# Our limit on the length of python names where we put
# them in CharFields -- python doesn't impose a limit, so this
# is pretty arbitrary
MAX_NAME_LENGTH = 128


class StoragePluginRecord(models.Model):
    """Reference to a module defining a StoragePlugin subclass"""
    module_name = models.CharField(max_length = MAX_NAME_LENGTH)

    class Meta:
        unique_together = ('module_name',)
        app_label = 'configure'


class StorageResourceClass(models.Model):
    """Reference to a StorageResource subclass"""
    storage_plugin = models.ForeignKey(StoragePluginRecord)
    class_name = models.CharField(max_length = MAX_NAME_LENGTH)

    def __str__(self):
        return "%s/%s" % (self.storage_plugin.module_name, self.class_name)

    def get_class(self):
        from configure.lib.storage_plugin.manager import storage_plugin_manager
        return storage_plugin_manager.get_resource_class_by_id(self.pk)

    class Meta:
        unique_together = ('storage_plugin', 'class_name')
        app_label = 'configure'

    def to_dict(self):
        resource_klass = self.get_class()

        fields = []
        for name, attr in resource_klass.get_all_attribute_properties():
            fields.append({
                'label': attr.get_label(name),
                'name': name,
                'optional': attr.optional,
                'class': attr.__class__.__name__})

        return {'plugin_name': self.storage_plugin.module_name,
                'class_name': self.class_name,
                'fields': fields,
                'label': "%s-%s" % (self.storage_plugin.module_name, self.class_name)}


class StorageResourceRecord(models.Model):
    """Reference to an instance of a StorageResource"""
    resource_class = models.ForeignKey(StorageResourceClass)

    # Representing a configure.lib.storage_plugin.GlobalId or LocalId
    # TODO: put some checking for id_strs longer than this field: they
    # are considered 'unreasonable' and plugin authors should be
    # conservative in what they use for an ID
    storage_id_str = models.CharField(max_length = 256)
    storage_id_scope = models.ForeignKey('StorageResourceRecord',
            blank = True, null = True)

    # XXX aargh when the id_scope is nullable a unique_together across it
    # doesn't enforce uniqueness for GlobalID resources

    # Parent-child relationships between resources
    parents = models.ManyToManyField('StorageResourceRecord',
            related_name = 'resource_parent')

    alias = models.CharField(max_length = 64, blank = True, null = True)

    class Meta:
        app_label = 'configure'
        unique_together = ('storage_id_str', 'storage_id_scope', 'resource_class')

    def __str__(self):
        return self.alias_or_name()

    def to_dict(self):
        resource = self.to_resource()

        from configure.lib.storage_plugin.query import ResourceQuery
        alerts = [a.to_dict() for a in ResourceQuery().resource_get_alerts(resource)]
        prop_alerts = [a.to_dict() for a in ResourceQuery().resource_get_propagated_alerts(resource)]

        from configure.models import StorageResourceStatistic
        stats = {}
        for s in StorageResourceStatistic.objects.filter(storage_resource = self):
            stats[s.name] = s.to_dict()

        from configure.lib.storage_plugin.resource import ScannableResource
        scannable = isinstance(resource, ScannableResource)

        return {'id': self.pk,
                'content_type_id': ContentType.objects.get_for_model(self).id,
                'class_name': resource.get_class_label(),
                'scannable': scannable,
                'alias': self.alias,
                'default_alias': resource.get_label(),
                'attributes': resource.get_attribute_items(),
                'alerts': alerts,
                'stats': stats,
                'charts': resource.get_charts(),
                'propagated_alerts': prop_alerts}

    @classmethod
    def get_or_create_root(cls, resource_class, resource_class_id, attrs):
        # Root resource do not have parents so they must be globally identified
        from configure.lib.storage_plugin.resource import GlobalId
        if not isinstance(resource_class.identifier, GlobalId):
            raise RuntimeError("Cannot create root resource of class %s, it is not globally identified" % resource_class)

        # NB assumes that none of the items in ID tuple are ResourceReferences: this
        # would raise an exception from json encoding.
        # FIXME: weird separate code path for creating resources (cf resourcemanager)
        import json
        id_str = json.dumps(resource_class.attrs_to_id_tuple(attrs))
        try:
            # See if you're trying to create something which already exists
            existing_record = StorageResourceRecord.objects.get(
                    resource_class = resource_class_id,
                    storage_id_str = id_str,
                    storage_id_scope = None)
            return existing_record, False
        except StorageResourceRecord.DoesNotExist:
            # Great, nothing in the way
            pass

        record = StorageResourceRecord(
                resource_class_id = resource_class_id,
                storage_id_str = id_str)
        record.save()
        for name, value in attrs.items():
            StorageResourceAttribute.objects.create(resource = record,
                    key = name, value = resource_class.encode(name, value))

        return record, True

    def update_attribute(self, key, val):
        from configure.lib.storage_plugin.manager import storage_plugin_manager
        resource_class = storage_plugin_manager.get_resource_class_by_id(self.resource_class_id)

        # Try to update an existing record
        updated = StorageResourceAttribute.objects.filter(
                    resource = self,
                    key = key).update(value = resource_class.encode(key, val))
        # If there was no existing record, create one
        if updated == 0:
            from django.db import IntegrityError
            try:
                StorageResourceAttribute.objects.create(
                        resource = self,
                        key = key,
                        value = resource_class.encode(key, val))
            except IntegrityError:
                # Collided with another update, order undefined so let him win
                pass

    def delete_attribute(self, attr_name):
        try:
            StorageResourceAttribute.objects.get(
                    resource = self,
                    key = attr_name).delete()
        except StorageResourceAttribute.DoesNotExist:
            pass

    def items(self):
        for i in self.storageresourceattribute_set.all():
            yield (i.key, i.value)

    def to_resource(self):
        from configure.lib.storage_plugin.manager import storage_plugin_manager
        klass = storage_plugin_manager.get_resource_class_by_id(self.resource_class_id)
        storage_dict = {}
        for attr in self.storageresourceattribute_set.all():
            storage_dict[attr.key] = klass.decode(attr.key, attr.value)
        resource = klass(**storage_dict)
        resource._handle = self.id
        resource._handle_global = True
        return resource

    def alias_or_name(self, resource = None):
        if self.alias:
            return self.alias
        else:
            if not resource:
                resource = self.to_resource()
            return resource.get_label()

    def to_resource_class(self):
        from configure.lib.storage_plugin.manager import storage_plugin_manager
        klass, klass_id = storage_plugin_manager.get_plugin_resource_class(
                self.resource_class.storage_plugin.module_name,
                self.resource_class.class_name)
        return klass

    def get_statistic_properties(self, stat_name):
        from configure.lib.storage_plugin.manager import storage_plugin_manager
        klass, klass_id = storage_plugin_manager.get_plugin_resource_class(
                self.resource_class.storage_plugin.module_name,
                self.resource_class.class_name)

        return klass._storage_statistics[stat_name]


class SimpleHistoStoreBin(models.Model):
    histo_store_time = models.ForeignKey('SimpleHistoStoreTime')
    bin_idx = models.IntegerField()
    value = models.PositiveIntegerField()

    class Meta:
        app_label = 'configure'


class SimpleHistoStoreTime(models.Model):
    storage_resource_statistic = models.ForeignKey('StorageResourceStatistic')
    time = models.PositiveIntegerField()

    class Meta:
        app_label = 'configure'


class SimpleScalarStoreDatapoint(models.Model):
    storage_resource_statistic = models.ForeignKey('StorageResourceStatistic')
    time = models.PositiveIntegerField()
    value = models.BigIntegerField()

    class Meta:
        app_label = 'configure'


class StorageResourceStatistic(models.Model):
    class Meta:
        unique_together = ('storage_resource', 'name')
        app_label = 'configure'

    storage_resource = models.ForeignKey(StorageResourceRecord)
    sample_period = models.IntegerField()
    name = models.CharField(max_length = 64)

    def delete(self, *args, **kwargs):
        # TODO: delete VendorMetricStore
        super(StorageResourceStatistic, self).delete(*args, **kwargs)

    def __get_metrics(self):
        from monitor.metrics import VendorMetricStore
        if not hasattr(self, '_metrics'):
            self._metrics = VendorMetricStore(self, self.sample_period)
        return self._metrics
    metrics = property(__get_metrics)

    def update(self, stat_name, stat_properties, stat_data):
        from configure.lib.storage_plugin import statistics
        if isinstance(stat_properties, statistics.BytesHistogram):
            for dp in stat_data:
                ts = dp['timestamp']
                bin_vals = dp['value']
                from django.db import transaction
                with transaction.commit_on_success():
                    time = SimpleHistoStoreTime.objects.create(time = ts, storage_resource_statistic = self)
                    for i in range(0, len(stat_properties.bins)):
                        SimpleHistoStoreBin.objects.create(bin_idx = i, value = bin_vals[i], histo_store_time = time)
        else:
            for dp in stat_data:
                ts = dp['timestamp']
                val = dp['value']
                SimpleScalarStoreDatapoint.objects.create(
                        time = ts,
                        value = val,
                        storage_resource_statistic = self)
        #self.metrics.update(stat_name, stat_properties, stat_data)

    def to_dict(self):
        """For use with frontend.  Get a time series for scalars or a snapshot for histograms.
        TODO: generalisation for explorable graphs, variable time series, that
        should be done in common with the lustre graphs."""
        from django.db import transaction
        stat_props = self.storage_resource.get_statistic_properties(self.name)
        from configure.lib.storage_plugin import statistics
        if isinstance(stat_props, statistics.BytesHistogram):
            with transaction.commit_manually():
                transaction.commit()
                try:
                    time = SimpleHistoStoreTime.objects.filter(storage_resource_statistic = self).latest('time')
                    bins = SimpleHistoStoreBin.objects.filter(histo_store_time = time).order_by('bin_idx')
                finally:
                    transaction.commit()
            type_name = 'histogram'
            # Composite type
            data = {'bin_labels': [], 'values': []}
            for i in range(0, len(stat_props.bins)):
                bin_info = u"\u2264%s" % stat_props.bins[i][1]
                data['bin_labels'].append(bin_info)
                data['values'].append(bins[i].value)
        else:
            with transaction.commit_manually():
                transaction.commit()
                try:
                    dps = SimpleScalarStoreDatapoint.objects\
                        .filter(storage_resource_statistic = self)\
                        .order_by('-time')[:100]
                    dps = list(dps)
                    dps.reverse()
                finally:
                    transaction.commit()
            type_name = 'timeseries'
            data_points = []
            for dp in dps:
                # Convert to ms for convenience with highcharts
                time_ms = dp.time * 1000
                data_points.append((time_ms, dp.value))

            data = {
                    'unit_name': stat_props.get_unit_name(),
                    'data_points': data_points
                    }

        label = stat_props.label
        if not label:
            label = self.name

        return {'name': self.name,
                'label': label,
                'type': type_name,
                'data': data}


class StorageResourceAttribute(models.Model):
    """An attribute of a StorageResource instance.

    Note that we store the denormalized key name of the attribute
    for each storageresource instance, to support schemaless attribute
    dictionaries.  If we made the executive decision to remove this
    and only allow explicitly declared fields, then we would normalize
    out the attribute names.
    """
    resource = models.ForeignKey(StorageResourceRecord)
    # TODO: specialized attribute tables for common types like
    # short strings, integers
    value = models.TextField()
    key = models.CharField(max_length = 64)

    class Meta:
        unique_together = ('resource', 'key')
        app_label = 'configure'


class StorageResourceClassStatistic(models.Model):
    resource_class = models.ForeignKey(StorageResourceClass)
    name = models.CharField(max_length = 64)

    class Meta:
        unique_together = ('resource_class', 'name')
        app_label = 'configure'


class StorageResourceStatistic(models.Model):
    resource = models.ForeignKey(StorageResourceRecord)
    resource_class_statistic = models.ForeignKey(StorageResourceClassStatistic)

    timestamp = models.DateTimeField()
    value = models.IntegerField()

    class Meta:
        app_label = 'configure'


class StorageResourceAlert(AlertState):
    """Used by configure.lib.storage_plugin"""

    # Within the plugin referenced by the alert_item, what kind
    # of alert is this?
    alert_class = models.CharField(max_length = 512)
    attribute = models.CharField(max_length = 128, blank = True, null = True)

    def __str__(self):
        return "<%s:%s %d>" % (self.alert_class, self.attribute, self.pk)

    def message(self):
        from configure.lib.storage_plugin.query import ResourceQuery
        msg = ResourceQuery().record_alert_message(self.alert_item.pk, self.alert_class)
        return msg

    def begin_event(self):
        import logging
        return AlertEvent(
                message_str = "Storage alert: %s" % self.message(),
                alert = self,
                severity = logging.WARNING)

    def end_event(self):
        import logging
        return AlertEvent(
                message_str = "Cleared storage alert: %s" % self.message(),
                alert = self,
                severity = logging.INFO)

    class Meta:
        app_label = 'configure'


class StorageAlertPropagated(models.Model):
    storage_resource = models.ForeignKey(StorageResourceRecord)
    alert_state = models.ForeignKey(StorageResourceAlert)

    class Meta:
        unique_together = ('storage_resource', 'alert_state')
        app_label = 'configure'


class StorageResourceLearnEvent(Event):
    storage_resource = models.ForeignKey(StorageResourceRecord)

    @staticmethod
    def type_name():
        return "Storage resource detection"

    def message(self):
        from configure.lib.storage_plugin.query import ResourceQuery
        class_name, instance_name = ResourceQuery().record_class_and_instance_string(self.storage_resource)
        return "Discovered %s '%s'" % (class_name, instance_name)

    class Meta:
        app_label = 'configure'
