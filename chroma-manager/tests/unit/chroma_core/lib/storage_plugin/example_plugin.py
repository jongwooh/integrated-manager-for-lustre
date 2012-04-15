from chroma_core.lib.storage_plugin.api import attributes, statistics
from chroma_core.lib.storage_plugin.api.identifiers import GlobalId, ScopedId
from chroma_core.lib.storage_plugin.api import resources
from chroma_core.lib.storage_plugin.api.plugin import Plugin


class Couplet(resources.ScannableResource):
    class Meta:
        identifier = GlobalId('address_1', 'address_2')

    address_1 = attributes.Hostname()
    address_2 = attributes.Hostname()


class Controller(resources.Controller):
    class Meta:
        identifier = ScopedId('index')

    index = attributes.Enum(0, 1)


class HardDrive(resources.PhysicalDisk):
    class Meta:
        identifier = ScopedId('serial_number')

    serial_number = attributes.String()
    capacity = attributes.Bytes()
    temperature = statistics.Gauge(units = 'C')


class RaidPool(resources.StoragePool):
    class Meta:
        identifier = ScopedId('local_id')

    local_id = attributes.Integer()
    raid_type = attributes.Enum('raid0', 'raid1', 'raid5', 'raid6')
    capacity = attributes.Bytes()

    def get_label(self):
        return self.local_id


class Lun(resources.LogicalDrive):
    class Meta:
        identifier = ScopedId('local_id')

    local_id = attributes.Integer()
    capacity = attributes.Bytes()
    name = attributes.String()

    scsi_id = attributes.String(provide = 'scsi_serial')

    def get_label(self):
        return self.name


class ExamplePlugin(Plugin):
    def initial_scan(self, scannable_resource):
        # This is where the plugin should detect all the resources
        # belonging to scannable_resource, or throw an exception
        # if that cannot be done.
        pass

    def update_scan(self, scannable_resource):
        # Update any changed or added/removed resources
        # Update any statistics
        pass

    def teardown(self):
        # Free any resources
        pass
