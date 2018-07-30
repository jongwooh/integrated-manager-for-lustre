# -*- coding: utf-8 -*-
# Copyright (c) 2018 DDN. All rights reserved.
# Use of this source code is governed by a MIT-style
# license that can be found in the LICENSE file.

from django.utils.timezone import now
from django.db import models

from chroma_core.models import DeletableStatefulObject
from chroma_core.models import NetworkInterface
from chroma_core.models import CorosyncStoppedAlert
from chroma_core.models import corosync_common
from chroma_core.lib.job import Step
from chroma_core.services.job_scheduler import job_scheduler_notify


class CorosyncConfiguration(DeletableStatefulObject):
    states = ['unconfigured', 'stopped', 'started']
    initial_state = 'unconfigured'

    host = models.OneToOneField('ManagedHost', related_name='_corosync_configuration')

    mcast_port = models.IntegerField(null=True)

    # Up from the point of view of a peer in the corosync cluster for this node
    corosync_reported_up = models.BooleanField(default=False,
                                               help_text="True if corosync on a node in this node's "
                                                         "cluster reports that this node is online")

    record_type = models.CharField(max_length = 128, default="CorosyncConfiguration")

    # THIS IS A TEMP HACK SO I DON'T HAVE TO DEVELOP THIS ON A BIG STACK OF PATCHES
    # IT WILL MAKE USE OF THE SPARSEMODEL TECHNOLOGY EVENTUALLY BUT FOR NOW WE SORT OF EMULATE IT.
    @classmethod
    def __new__(cls, *args, **kwargs):
        try:
            import chroma_core
            if kwargs != {}:
                if 'record_type' not in kwargs:
                    kwargs['record_type'] = cls.__name__
                required_class = getattr(chroma_core.models, kwargs['record_type'])
            else:
                if len(args) == 1:
                    required_class = cls
                else:
                    # The args will be in the order of the fields, but we add 1 because the cls is appended on the front.
                    record_type_index = [field.attname for field in cls._meta.fields].index('record_type') + 1
                    try:
                        required_class = getattr(chroma_core.models, args[record_type_index])
                    except:
                        pass

            if (cls != required_class):
                args = (required_class,) + args[1:]
                instance = required_class.__new__(*args, **kwargs)

                # We have to call init because python won't because we are returning a different type.
                instance.__init__(*args[1:], **kwargs)
            else:
                instance = super(CorosyncConfiguration, cls).__new__(cls)

            return instance
        except StopIteration:
            raise RuntimeError("CorosyncConfiguration %s unknown" % cls)

    def __init__(self, *args, **kwargs):
        if kwargs and 'record_type' not in kwargs:
            kwargs['record_type'] = self.__class__.__name__

        super(CorosyncConfiguration, self).__init__(*args, **kwargs)

        # Megahack, because we are on two tables for now.
        if hasattr(self, 'corosyncconfiguration_ptr_id'):
            self.corosyncconfiguration_ptr_id = self.id

    def __str__(self):
        return "%s Corosync configuration" % self.host

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_label(self):
        return "corosync configuration"

    def set_state(self, state, intentional = False):
        """
        :param intentional: set to true to silence any alerts generated by this transition
        """
        super(CorosyncConfiguration, self).set_state(state, intentional)
        if intentional:
            CorosyncStoppedAlert.notify_warning(self, self.state != 'started')
        else:
            CorosyncStoppedAlert.notify(self, self.state != 'started')

    reverse_deps = {
        'PacemakerConfiguration': lambda pc: CorosyncConfiguration.objects.filter(host_id = pc.host.id),
    }

    @property
    def network_interfaces(self):
        return [network_interface for network_interface in NetworkInterface.objects.filter(corosync_configuration = self)]

    @network_interfaces.setter
    def network_interfaces(self, interface_names):
        host_interfaces = NetworkInterface.objects.filter(host = self.host)

        for interface in host_interfaces:                               # Mark all interface_names as not corosync.
            if interface.corosync_configuration == self:
                interface.corosync_configuration = None

        for interface_name in interface_names:
            try:                                                        # Mark interface_names as corosync if it is existing.
                network_interface = next(network_interface for network_interface in host_interfaces if network_interface.name == interface_name)
                network_interface.corosync_configuration = self
            except StopIteration:
                pass

        for interface in host_interfaces:
            interface.save()

    @property
    def configure_job_name(self):
        return "ConfigureCorosyncJob"


class AutoConfigureCorosyncStep(Step):
    idempotent = True

    def run(self, kwargs):
        corosync_configuration = kwargs['corosync_configuration']

        config = self.invoke_agent_expect_result(corosync_configuration.host, "get_corosync_autoconfig")

        ring0_name, ring0_config = next((interface, config) for interface, config in config['interfaces'].items() if config['dedicated'] == False)
        ring1_name, ring1_config = next((interface, config) for interface, config in config['interfaces'].items() if config['dedicated'] == True)

        self.invoke_agent_expect_result(corosync_configuration.host,
                                        "configure_network",
                                        {'ring0_name': ring0_name,
                                         'ring1_name': ring1_name,
                                         'ring1_ipaddr': ring1_config['ipaddr'],
                                         'ring1_prefix': ring1_config['prefix']})

        self.invoke_agent_expect_result(corosync_configuration.host,
                                        "configure_corosync",
                                        {'ring0_name': ring0_name,
                                         'ring1_name': ring1_name,
                                         'old_mcast_port': corosync_configuration.mcast_port,
                                         'new_mcast_port': config['mcast_port']})

        job_scheduler_notify.notify(corosync_configuration,
                                    now(),
                                    {'mcast_port': config['mcast_port'],
                                     'network_interfaces': [ring0_name, ring1_name]})


class AutoConfigureCorosyncJob(corosync_common.AutoConfigureCorosyncJob):
    state_transition = corosync_common.AutoConfigureCorosyncJob.StateTransition(CorosyncConfiguration, 'unconfigured', 'stopped')
    corosync_configuration = models.ForeignKey(CorosyncConfiguration)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        return [(AutoConfigureCorosyncStep, {'corosync_configuration': self.corosync_configuration})]


class UnconfigureCorosyncStep(Step):
    idempotent = True

    def run(self, kwargs):
        self.invoke_agent_expect_result(kwargs['host'], "unconfigure_corosync")


class UnconfigureCorosyncJob(corosync_common.UnconfigureCorosyncJob):
    state_transition = corosync_common.UnconfigureCorosyncJob.StateTransition(CorosyncConfiguration, 'stopped', 'unconfigured')
    corosync_configuration = models.ForeignKey(CorosyncConfiguration)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        return [(UnconfigureCorosyncStep, {'host': self.corosync_configuration.host})]


class StartCorosyncStep(Step):
    idempotent = True

    def run(self, kwargs):
        self.invoke_agent_expect_result(kwargs['host'], "start_corosync")


class StartCorosyncJob(corosync_common.StartCorosyncJob):
    state_transition = corosync_common.StartCorosyncJob.StateTransition(CorosyncConfiguration, 'stopped', 'started')
    corosync_configuration = models.ForeignKey(CorosyncConfiguration)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        return [(StartCorosyncStep, {'host': self.corosync_configuration.host})]


class StopCorosyncStep(Step):
    idempotent = True

    def run(self, kwargs):
        self.invoke_agent_expect_result(kwargs['host'], "stop_corosync")


class StopCorosyncJob(corosync_common.StopCorosyncJob):
    state_transition = corosync_common.StopCorosyncJob.StateTransition(CorosyncConfiguration, 'started', 'stopped')
    corosync_configuration = models.ForeignKey(CorosyncConfiguration)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        return [(StopCorosyncStep, {'host': self.corosync_configuration.host})]


class ConfigureCorosyncStep(Step):
    idempotent = True
    database = True

    def run(self, kwargs):
        corosync_configuration = kwargs['corosync_configuration']

        self.invoke_agent_expect_result(corosync_configuration.host,
                                        "configure_corosync",
                                        {'ring0_name': kwargs['ring0_name'],
                                         'ring1_name': kwargs['ring1_name'],
                                         'old_mcast_port': kwargs['old_mcast_port'],
                                         'new_mcast_port': kwargs['new_mcast_port']})

        job_scheduler_notify.notify(corosync_configuration,
                                    now(),
                                    {'mcast_port': kwargs['new_mcast_port'],
                                     'network_interfaces': [kwargs['ring0_name'], kwargs['ring1_name']]})


class ConfigureCorosyncJob(corosync_common.ConfigureCorosyncJob):
    corosync_configuration = models.ForeignKey(CorosyncConfiguration)

    class Meta:
        app_label = 'chroma_core'
        ordering = ['id']

    def get_steps(self):
        steps = [(ConfigureCorosyncStep, {'corosync_configuration': self.corosync_configuration,
                                          'ring0_name': self.network_interface_0.name,
                                          'ring1_name': self.network_interface_1.name,
                                          'old_mcast_port': self.corosync_configuration.mcast_port,
                                          'new_mcast_port': self.mcast_port})]

        return steps
