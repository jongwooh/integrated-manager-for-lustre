

import logging
import socket
import time
import paramiko
import re

from testconfig import config
from tests.integration.core.constants import TEST_TIMEOUT
from tests.integration.core.utility_testcase import RemoteCommandResult


logger = logging.getLogger('test')
logger.setLevel(logging.DEBUG)


class RemoteOperations(object):
    """
    Actions occuring 'out of band' with respect to chroma manager, usually
    things which talk directly to a storage server or a lustre client rather
    than going via the chroma manager API.
    """

    def _address2server(self, address):
        for server in config['lustre_servers']:
            if server['address'] == address:
                return server

        raise RuntimeError('Unable to resolve %s as a server fqdn' % address)


class SimulatorRemoteOperations(RemoteOperations):
    def __init__(self, test_case, simulator):
        self._test_case = test_case
        self._simulator = simulator

    def host_contactable(self, address):
        cfg_server = self._address2server(address)
        sim_server = self._simulator.servers[cfg_server['fqdn']]
        if sim_server.running:
            return not sim_server.starting_up and not sim_server.shutting_down
        else:
            return False

    def erase_block_device(self, fqdn, path):
        self._simulator.format_block_device(fqdn, path, None)

    def format_block_device(self, fqdn, path, filesystem_type):
        self._simulator.format_block_device(fqdn, path, filesystem_type)

    def stop_target(self, fqdn, ha_label):
        self._simulator.get_cluster(fqdn).stop(ha_label)

    def start_target(self, fqdn, ha_label):
        self._simulator.get_cluster(fqdn).start(ha_label)

    def start_lnet(self, fqdn):
        self._simulator.servers[fqdn].start_lnet()

    def stop_lnet(self, fqdn):
        self._simulator.servers[fqdn].stop_lnet()

    def backup_cib(*args, **kwargs):
        return []

    def restore_cib(*args, **kwargs):
        pass

    def set_node_standby(*args, **kwargs):
        pass

    def set_node_online(*args, **kwargs):
        pass

    def read_proc(self, address, path):
        fqdn = None
        for server in config['lustre_servers']:
            if server['address'] == address:
                fqdn = server['fqdn']

        lustre_clients = [c['address'] for c in config['lustre_clients']]
        if fqdn is None and not address in lustre_clients:
            raise KeyError("No server with address %s" % address)
        elif fqdn is None and address in lustre_clients:
            client = self._simulator.get_lustre_client(address)
            return client.read_proc(path)
        else:
            return self._simulator.servers[fqdn].read_proc(path)

    def mount_filesystem(self, client_address, filesystem):
        client = self._simulator.get_lustre_client(client_address)
        mgsnode, fsname = filesystem['mount_path'].split(":/")
        client.mount(mgsnode, fsname)

    def unmount_filesystem(self, client_address, filesystem):
        client = self._simulator.get_lustre_client(client_address)
        mgsnode, fsname = filesystem['mount_path'].split(":/")
        client.unmount(mgsnode, fsname)

    def get_resource_running(self, host, ha_label):
        actual = self._simulator.get_cluster(host['fqdn']).resource_locations()[ha_label]
        expected = host['nodename']
        logger.debug("get_resource_running: %s %s %s" % (ha_label, actual, expected))
        return actual == expected

    def check_ha_config(self, hosts, filesystem):
        # TODO check self._simulator.get_cluster(fqdn) for some resources
        # configured on these hosts withthe filesystem name in them
        pass

    def exercise_filesystem(self, client_address, filesystem):
        # TODO: do a check that the client has the filesystem mounted
        # and that the filesystem targets are up
        pass

    def reset_server(self, fqdn):
        self._simulator.reboot_server(fqdn)

    def kill_server(self, fqdn):
        self._simulator.stop_server(fqdn, shutdown = True)

    def await_server_boot(self, boot_fqdn, monitor_fqdn = None, restart = True):
        server = self._simulator.servers[boot_fqdn]
        if not server.registered:
            logger.warn("Can't start %s; not registered" % boot_fqdn)
            return

        restart_attempted = False
        running_time = 0
        while not self.host_contactable(boot_fqdn) and running_time < TEST_TIMEOUT:
            # Restart signals that a stopped server should be restarted here.
            # Otherwise, we'll just wait for it to (re-)boot, hoping that this
            # was initiated elsewhere.
            if restart and not restart_attempted:
                restart_attempted = True
                self._simulator.start_server(boot_fqdn)

            running_time += 1
            time.sleep(1)

        self._test_case.assertLess(running_time, TEST_TIMEOUT, "Timed out waiting for %s to boot" % boot_fqdn)

    def unmount_clients(self):
        self._simulator.unmount_lustre_clients()

    def remove_config(self, *args):
        pass

    def write_config(self, *args):
        pass

    def clear_ha(self, *args):
        self._simulator.clear_clusters()

    def inject_log_message(self, fqdn, message):
        self._simulator.servers[fqdn].inject_log_message(message)

    def install_upgrades(self):
        # We don't actually modify the manager here, rather we cause the
        # agents to report that they are seeing higher versions of available
        # packages
        self._simulator.update_packages({
            'lustre': (0, '2.9.0', '1', 'x86_64')
        })

    def get_package_version(self, fqdn, package):
        return self._simulator.servers[fqdn].get_package_version(package)

    def enable_agent_debug(self, server_list):
        # Already handled elsewhere
        pass

    def disable_agent_debug(self, server_list):
        pass


class RealRemoteOperations(RemoteOperations):
    def __init__(self, test_case):
        self._test_case = test_case

    # TODO: reconcile this with the one in UtilityTestCase, ideally all remote
    # operations would flow through here to avoid rogue SSH calls
    def _ssh_address(self, address, command, expected_return_code=0, timeout=TEST_TIMEOUT, buffer=None):
        """
        Executes a command on a remote server over ssh.

        Sends a command over ssh to a remote machine and returns the stdout,
        stderr, and exit status. It will verify that the exit status of the
        command matches expected_return_code unless expected_return_code=None.
        """
        logger.debug("remote_command[%s]: %s" % (address, command))
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        args = {'username': 'root'}
        # If given an ssh_config file, require that it defines
        # a private key and username for accessing this host
        config_path = config.get('ssh_config', None)
        if config_path:
            ssh_config = paramiko.SSHConfig()
            ssh_config.parse(open(config_path))

            host_config = ssh_config.lookup(address)
            address = host_config['hostname']

            if 'user' in host_config:
                args['username'] = host_config['user']
                if args['username'] != 'root':
                    command = "sudo sh -c \"{}\"".format(command.replace('"', '\\"'))

            if 'identityfile' in host_config:
                args['key_filename'] = host_config['identityfile'][0]

                # Work around paramiko issue 157, failure to parse quoted values
                # (vagrant always quotes IdentityFile)
                args['key_filename'] = args['key_filename'].strip("\"")

        logger.info("SSH address = %s, args = %s" % (address, args))

        ssh.connect(address, **args)
        transport = ssh.get_transport()
        transport.set_keepalive(20)
        channel = transport.open_session()
        channel.settimeout(timeout)
        channel.exec_command(command)
        if buffer:
            stdin = channel.makefile('wb')
            stdin.write(buffer)
            stdin.flush()
            stdin.channel.shutdown_write()
        stdout = channel.makefile('rb')
        stderr = channel.makefile_stderr()
        exit_status = channel.recv_exit_status()
        if expected_return_code is not None:
            self._test_case.assertEqual(exit_status, expected_return_code, stderr.read())
        return RemoteCommandResult(exit_status, stdout, stderr)

    def _ssh_fqdn(self, fqdn, command, expected_return_code=0, timeout = TEST_TIMEOUT):
        address = None
        for host in config['lustre_servers']:
            if host['fqdn'] == fqdn:
                address = host['address']
        if address is None:
            raise KeyError(fqdn)

        return self._ssh_address(address, command, expected_return_code, timeout)

    def erase_block_device(self, fqdn, path):
        # Needless to say, we're not bothering to scrub the whole device, just enough
        # that it doesn't look formatted any more.
        self._ssh_fqdn(fqdn, "dd if=/dev/zero of={path} bs=4k count=1; sync".format(path=path))

    def format_block_device(self, fqdn, path, filesystem_type):
        commands = {
            'ext2': "mkfs.ext2 -F '{path}'".format(path=path),
            'lustre': "mkfs.lustre --mgs '{path}'".format(path=path)
        }
        try:
            command = commands[filesystem_type]
        except KeyError:
            raise RuntimeError("Unknown filesystem type %s (known types are %s)" % (filesystem_type, commands.keys()))

        self._ssh_fqdn(fqdn, command)

    def stop_target(self, fqdn, ha_label):
        self._ssh_fqdn(fqdn, "chroma-agent stop_target --ha %s" % ha_label)

    def start_target(self, fqdn, ha_label):
        self._ssh_fqdn(fqdn, "chroma-agent start_target --ha %s" % ha_label)

    def stop_lnet(self, fqdn):
        self._ssh_fqdn(fqdn, "chroma-agent stop_lnet")

    def start_lnet(self, fqdn):
        self._ssh_fqdn(fqdn, "chroma-agent start_lnet")

    def inject_log_message(self, fqdn, message):
        self._ssh_fqdn(fqdn, "logger \"%s\"" % message)

    def read_proc(self, address, path):
        result = self._ssh_address(address, "cat %s" % path)
        return result.stdout.read().strip()

    def backup_cib(self, server, backup="/tmp/cib-backup.xml"):
        running_targets = self.get_pacemaker_targets(server, running = True)
        for target in running_targets:
            self.stop_target(server['fqdn'], target)

        self._test_case.wait_until_true(lambda: len(self.get_pacemaker_targets(server, running = True)) < 1)

        self._ssh_fqdn(server['fqdn'],
                       '''cibadmin --query | sed -e 's/epoch="[[:digit:]]\+" //'> %s''' % backup)

        return running_targets

    def restore_cib(self, server, start_targets, restore="/tmp/cib-backup.xml"):
        self._ssh_fqdn(server['fqdn'], "cibadmin --erase --force")
        self._ssh_fqdn(server['fqdn'], "cibadmin --modify --xml-file %s" % restore)
        for target in start_targets:
            self.start_target(server['fqdn'], target)

        self._test_case.wait_until_true(lambda: len(self.get_pacemaker_targets(server, running = True)) == len(start_targets))

    # HYD-2071: These two methods may no longer be useful after the API-side
    # work lands.
    def set_node_standby(self, server):
        self._ssh_address(server['address'],
                          "chroma-agent set_node_standby --node %s" % server['nodename'])

    def set_node_online(self, server):
        self._ssh_address(server['address'],
                          "chroma-agent set_node_online --node %s" % server['nodename'])

    def mount_filesystem(self, client_address, filesystem):
        """
        Mounts a lustre filesystem on a specified client.
        """
        self._ssh_address(
            client_address,
            "mkdir -p /mnt/%s" % filesystem['name']
        )

        self._ssh_address(
            client_address,
            filesystem['mount_command']
        )

        result = self._ssh_address(
            client_address,
            'mount'
        )
        self._test_case.assertRegexpMatches(
            result.stdout.read(),
            "%s on /mnt/%s " % (filesystem['mount_path'], filesystem['name'])
        )

    def _unmount_filesystem(self, client, filesystem_name):
        """
        Unmounts a lustre filesystem from the specified client if mounted.
        """
        result = self._ssh_address(
            client,
            'mount'
        )
        if re.search(" on /mnt/%s " % filesystem_name, result.stdout.read()):
            logger.debug("Unmounting %s" % filesystem_name)
            self._ssh_address(
                client,
                "umount /mnt/%s" % filesystem_name
            )
        result = self._ssh_address(
            client,
            'mount'
        )
        mount_output = result.stdout.read()
        logger.debug("`Mount`: %s" % mount_output)
        self._test_case.assertNotRegexpMatches(
            mount_output,
            " on /mnt/%s " % filesystem_name
        )

    def unmount_filesystem(self, client_address, filesystem):
        """
        Unmounts a lustre filesystem from the specified client if mounted.
        """
        self._unmount_filesystem(client_address, filesystem['name'])

    def get_resource_running(self, host, ha_label):
        result = self._ssh_address(
            host['address'],
            'crm resource status %s' % ha_label,
            timeout = 30  # shorter timeout since shouldnt take long and increases turnaround when there is a problem
        )
        resource_status = result.stdout.read()

        # Sometimes crm resource status gives a false positive when it is repetitively
        # trying to restart a resource over and over. Lets also check the failcount
        # to check that it didn't have problems starting.
        result = self._ssh_address(
            host['address'],
            'crm resource failcount %s show %s' % (ha_label, host['nodename'])
        )
        self._test_case.assertRegexpMatches(
            result.stdout.read(),
            'value=0'
        )

        # Check pacemaker thinks it's running on the right host.
        expected_resource_status = "%s is running on: %s" % (ha_label, host['nodename'])

        return bool(re.search(expected_resource_status, resource_status))

    def check_ha_config(self, hosts, filesystem):
        for host in hosts:
            result = self._ssh_address(
                host['address'],
                'crm configure show'
            )
            configuration = result.stdout.read()
            self._test_case.assertRegexpMatches(
                configuration,
                "location [^\n]* %s\n" % host['nodename']
            )
            self._test_case.assertRegexpMatches(
                configuration,
                "primitive %s-" % filesystem['name']
            )
            self._test_case.assertRegexpMatches(
                configuration,
                "id=\"%s-" % filesystem['name']
            )

    def exercise_filesystem(self, client_address, filesystem):
        """
        Verify we can actually exercise a filesystem.

        Currently this only verifies that we can write to a filesystem as a
        sanity check that it was configured correctly.
        """
        # TODO: Expand on this. Perhaps use existing lustre client tests.
        if filesystem.get('bytes_free') is None:
            self._test_case.wait_until_true(lambda: self._test_case.get_filesystem(filesystem['id']).get('bytes_free') is not None)
            filesystem = self._test_case.get_filesystem(filesystem['id'])

        self._ssh_address(
            client_address,
            "dd if=/dev/zero of=/mnt/%s/exercisetest.dat bs=1000 count=%s" % (
                filesystem['name'],
                min((filesystem.get('bytes_free') * 0.4), 512000) / 1000
            )
        )

    def _fqdn_to_server_config(self, fqdn):
        for server in config['lustre_servers']:
            if server['fqdn'] == fqdn:
                return server

        raise RuntimeError("No server config for %s" % fqdn)

    def host_contactable(self, address):
        try:
            #TODO: Better way to check this?
            result = self._ssh_address(
                address,
                "echo 'Checking if node is ready to receive commands.'",
                expected_return_code=None
            )

        except socket.error:
            return False
        except paramiko.AuthenticationException, e:
            logger.debug("Auth error when checking %s: %s" % (address, e))
            return False
        else:
            return True

        if not result.exit_status == 0:
            # Wait, what?  echo returned !0?  How is that possible?
            return False

    def host_up_secs(self, address):
        result = self._ssh_address(address, "cat /proc/uptime")
        secs_up = result.stdout.read().split()[0]
        return secs_up

    def _host_of_server(self, server):
        return config['hosts'][server['host']]

    def reset_server(self, fqdn):
        # NB: This is a vaguely dangerous operation -- basically the
        # equivalent of hitting the reset button. It's not a nice
        # shutdown that gives the fs time to sync, etc.
        server_config = self._fqdn_to_server_config(fqdn)
        host = self._host_of_server(server_config)
        reset_cmd = server_config.get('reset_command', None)
        if host.get('reset_is_buggy', False):
            self.kill_server(fqdn)
            self.await_server_boot(fqdn, restart = True)
        elif reset_cmd:
            result = self._ssh_address(
                server_config['host'],
                reset_cmd,
                ssh_key_file = server_config.get('ssh_key_file', None)
            )
            node_status = result.stdout.read()
            if re.search('was reset', node_status):
                logger.info("%s reset successfully" % fqdn)
        else:
            self._ssh_address(server_config['address'],
                              '''
                              echo 1 > /proc/sys/kernel/sysrq;
                              echo b > /proc/sysrq-trigger
                              ''', expected_return_code = -1)

    def kill_server(self, fqdn):
        # "Pull the plug" on host
        server_config = self._fqdn_to_server_config(fqdn)
        self._ssh_address(
            server_config['host'],
            server_config['destroy_command']
        )

        i = 0
        last_secs_up = 0
        while self.host_contactable(server_config['address']):
            # plug a race where the host comes up fast enough to allow ssh to
            # plow through
            secs_up = self.host_up_secs(server_config['address'])
            if secs_up < last_secs_up:
                return

            last_secs_up = secs_up

            i += 1
            time.sleep(1)
            if i > TEST_TIMEOUT:
                raise RuntimeError("Host %s didn't terminate within %s seconds" % (fqdn, TEST_TIMEOUT))

    def await_server_boot(self, boot_fqdn, monitor_fqdn = None, restart = False):
        """
        Wait for the stonithed server to come back online
        """
        boot_server = self._fqdn_to_server_config(boot_fqdn)
        monitor_server = None if monitor_fqdn is None else self._fqdn_to_server_config(monitor_fqdn)
        restart_attempted = False

        running_time = 0
        while running_time < TEST_TIMEOUT:
            if self.host_contactable(boot_server['address']):
                # If we have a peer to check then fall through to that, else
                # drop out here
                if monitor_server:
                    # Verify other host knows it is no longer offline
                    result = self._ssh_address(
                        monitor_server['address'],
                        "crm node show %s" % boot_server['nodename']
                    )
                    node_status = result.stdout.read()
                    if not re.search('offline', node_status):
                        break
                else:
                    # No monitor server, take SSH offline-ness as evidence for being booted
                    break
            else:
                if restart and not restart_attempted:
                    logger.info("attempting to restart %s" % boot_fqdn)
                    result = self._ssh_address(
                        boot_server['host'],
                        boot_server['status_command']
                    )
                    node_status = result.stdout.read()
                    if re.search('running', node_status):
                        logger.info("%s seems to be running, but unresponsive" % boot_fqdn)
                        self.kill_server(boot_fqdn)
                    result = self._ssh_address(
                        boot_server['host'],
                        boot_server['start_command']
                    )
                    node_status = result.stdout.read()
                    if re.search('started', node_status):
                        logger.info("%s started successfully" % boot_fqdn)
                    restart_attempted = True

            time.sleep(3)
            running_time += 3

        self._test_case.assertLess(running_time, TEST_TIMEOUT, "Timed out waiting for host to come back online.")
        if monitor_server:
            result = self._ssh_address(
                monitor_server['address'],
                "crm node show %s" % boot_server['nodename']
            )
            self._test_case.assertNotRegexpMatches(result.stdout.read(), 'offline')

    def unmount_clients(self):
        """
        Unmount all filesystems of type lustre from all clients in the config.
        """
        for client in config['lustre_clients']:
            self._ssh_address(
                client['address'],
                'umount -t lustre -a'
            )
            if not client in [server['address'] for server in config['lustre_servers']]:
                # Skip this check if the client is also a server, because
                # both targets and clients look like 'lustre' mounts
                result = self._ssh_address(
                    client['address'],
                    'mount'
                )
                self._test_case.assertNotRegexpMatches(
                    result.stdout.read(),
                    " type lustre"
                )

    def has_pacemaker(self, server):
        result = self._ssh_address(
            server['address'],
            'which crmadmin',
            expected_return_code = None
        )
        return result.exit_status == 0

    def get_pacemaker_targets(self, server, running = False):
        """
        Returns a list of chroma targets configured in pacemaker on a server.
        :param running: Restrict the returned list only to running targets.
        """
        result = self._ssh_address(
            server['address'],
            'crm resource list'
        )
        crm_resources = result.stdout.read().split('\n')
        targets = []
        for r in crm_resources:
            if not re.search('chroma:Target', r):
                continue

            target = r.split()[0]
            if running and re.search('Started\s*$', r):
                targets.append(target)
            elif not running:
                targets.append(target)
        return targets

    def is_pacemaker_target_running(self, server, target):
        result = self._ssh_address(
            server['address'],
            "crm resource status %s" % target
        )
        return re.search('is running', result.stdout.read())

    def get_fence_nodes_list(self, address):
        result = self._ssh_address(address, "fence_chroma -o list")
        # -o list returns:
        # host1,\n
        # host2,\n
        # ...
        return [name[:-2] for name in result.stdout.readlines()]

    def remove_config(self, server_list):
        """
        Remove /etc/chroma.cfg on the test servers.
        """
        for server in server_list:
            self._ssh_address(server['address'], 'rm -f /etc/chroma.cfg')

    def write_config(self, server_list):
        """
        Write out /etc/chroma.cfg on the test servers.
        """
        from ConfigParser import SafeConfigParser
        from StringIO import StringIO

        sections = ['corosync']

        for server in server_list:
            config = SafeConfigParser()
            for section in sections:
                config_key = "%s_config" % section
                if config_key in server:
                    config.add_section(section)
                    for key, val in server[config_key].items():
                        config.set(section, key, val)
            cfg_str = StringIO()
            config.write(cfg_str)

            if len(cfg_str.getvalue()) > 0:
                self._ssh_address(
                    server['address'],
                    'cat > /etc/chroma.cfg',
                    buffer = cfg_str.getvalue()
                )
                # Make sure the config gets to disk!
                self._ssh_address(
                    server['address'],
                    'sync; sync',
                    buffer = cfg_str.getvalue()
                )

    def clear_ha(self, server_list):
        """
        Stops and deletes all chroma targets for any corosync clusters
        configured on any of the lustre servers appearing in the cluster config
        """

        for server in server_list:
            if self.has_pacemaker(server):
                if config.get('pacemaker_hard_reset', False):
                    result = self._ssh_address(
                        server['address'],
                        '''set -ex
                        service pacemaker stop &
                        pid=$!
                        timeout=120
                        while kill -0 $pid && [ $timeout -gt 0 ]; do
                            sleep 1
                            let timeout=$timeout-1 || true
                        done
                        if kill -0 $pid; then
                            # now start getting all medevil on it
                            killall crmd
                            timeout=5
                            while killall -0 crmd && [ $timeout -gt 0 ]; do
                                sleep 1
                                let timeout=$timeout-1 || true
                            done
                            if killall -0 crmd; then
                                # hrm.  what to do now?
                                echo "even killing crmd didn't work" >&2
                            fi
                        fi
                        service corosync stop
                        ifconfig eth1 0.0.0.0 down
                        rm -f /etc/sysconfig/network-scripts/ifcfg-eth1
                        rm -f /etc/corosync/corosync.conf
                        rm -f /var/lib/heartbeat/crm/* /var/lib/corosync/*;
                        cat << EOF > /etc/sysconfig/system-config-firewall
--enabled
--port=22:tcp
--port=988:tcp
EOF
                        lokkit -n >&2
                        service iptables restart >&2
                        if grep lustre /proc/mounts >&2; then
                            if ! service pacemaker status >&2; then
                                rc=${PIPESTATUS[0]}
                            else
                                rc=0
                            fi
                            echo $rc >&2
                            if [ $rc = 3 ]; then
                                # pacemaker is actually stopped, stop lustre targets
                                umount -t lustre -a >&2
                            else
                                ps axf >&2
                                exit $rc
                            fi
                        fi
                        ''', None
                    )
                    logger.info(result.stderr.read())
                    self._test_case.assertEqual(result.exit_status, 0)
                else:
                    crm_targets = self.get_pacemaker_targets(server)

                    # Stop targets and delete targets
                    for target in crm_targets:
                        self._ssh_address(server['address'], 'crm resource stop %s' % target)
                    for target in crm_targets:
                        self._test_case.wait_until_true(lambda: not self.is_pacemaker_target_running(server, target))
                        self._ssh_address(server['address'], 'crm configure delete %s' % target)
                        self._ssh_address(server['address'], 'crm resource cleanup %s' % target)

                    # Verify no more targets
                    self._test_case.wait_until_true(lambda: not self.get_pacemaker_targets(server))

                    # remove firewall rules added for corosync
                    mcastport = self.get_corosync_port(server)
                    if mcastport:
                        self.del_firewall_rule(server, mcastport, "udp")

                rpm_q_result = self._ssh_address(server['address'], "rpm -q chroma-agent", expected_return_code=None)
                if rpm_q_result.exit_status == 0:
                    # Stop the agent
                    self._ssh_address(
                        server['address'],
                        'service chroma-agent stop'
                    )
                    self._ssh_address(
                        server['address'],
                        '''
                        rm -rf /var/lib/chroma/*;
                        rm -f /var/log/chroma-*.log
                        ''',
                        expected_return_code = None  # Keep going if it failed - may be none there.
                    )
            else:
                logger.info("%s does not appear to have pacemaker - skipping any removal of targets." % server['address'])

    def install_upgrades(self):
        raise NotImplementedError("Automated test of upgrades is HYD-1739")

    def get_package_version(self, fqdn, package):
        raise NotImplementedError("Automated test of upgrades is HYD-1739")

    def get_iptables_rules(self, server):
        rules = []
        for line in self._ssh_address(server['address'],
                                      "iptables -L INPUT -nv").stdout.readlines()[2:]:
            logger.info(line.rstrip())
            rule = {}
            try:
                # 0 0 ACCEPT udp  -- * * 0.0.0.0/0 0.0.0.0/0 state NEW udp dpt:123
                (rule["pkts"], rule["bytes"], rule["target"], rule["prot"],
                 rule["opt"], rule["in"], rule["out"], rule["source"],
                 rule["destination"], rule["details"]) = line.rstrip().split(None, 9)
            except ValueError:
                # 0 0 ACCEPT icmp -- * * 0.0.0.0/0 0.0.0.0/0
                (rule["pkts"], rule["bytes"], rule["target"], rule["prot"],
                 rule["opt"], rule["in"], rule["out"], rule["source"],
                 rule["destination"]) = line.rstrip().split()
            rules.append(rule)

        return rules

    def get_corosync_port(self, server):
        mcastport = None
        for line in self._ssh_address(server['address'],
                                      "cat /etc/corosync/corosync.conf || true").stdout.readlines():
            match = re.match("\s*mcastport:\s*(\d+)", line)
            if match:
                mcastport = match.group(1)
                break

        return mcastport

    def grep_file(self, server, string, file):
        result = self._ssh_address(server['address'],
                                   "grep -e \"%s\" %s || true" %
                                   (string, file)).stdout.read()
        return result

    def get_file_content(self, server, file):
        result = self._ssh_address(server['address'], "cat \"%s\" || true" %
                                                      file).stdout.read()
        return result

    def del_firewall_rule(self, server, port, proto):
        # it really bites that lokkit has no "delete" functionality
        self._ssh_address(server['address'], """set -ex
if service iptables status && iptables -L INPUT -nv | grep 'state NEW %s dpt:%s'; then
    iptables -D INPUT -m state --state new -p %s --dport %s -j ACCEPT
fi
sed -i -e '/-A INPUT -m state --state NEW -m %s -p %s --dport %s -j ACCEPT/d' /etc/sysconfig/iptables
sed -i -e '/--port=%s:%s/d' /etc/sysconfig/system-config-firewall""" %
                          (proto, port, proto, port, proto, proto, port, port, proto))

    def enable_agent_debug(self, server_list):
        for server in server_list:
            self._ssh_address(server['address'],
                              "touch /tmp/chroma-agent-debug")

    def disable_agent_debug(self, server_list):
        for server in server_list:
            self._ssh_address(server['address'],
                              "rm -f /tmp/chroma-agent-debug")

    def omping(self, server, servers, count=5, timeout=30):
        r = self._ssh_address(server['address'], """exec 2>&1
iptables -I INPUT -p udp --dport 4321 -j ACCEPT
omping -T %s -c %s %s
iptables -D INPUT -p udp --dport 4321 -j ACCEPT""" % (timeout, count,
                              " ".join([s['nodename'] for s in servers])))
        mc_replies = 0
        stdout = r.stdout.read()
        for line in stdout.split('\n'):
            if "multicast, seq=" in line:
                mc_replies += 1

        return mc_replies, stdout
