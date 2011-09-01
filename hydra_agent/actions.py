#
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

""" Library of actions that the hydra-agent can be asked to carry out."""

from hydra_agent.legacy_audit import LocalLustreAudit
import sys
import errno
import os
import shlex, subprocess
import simplejson as json

LIBDIR = "/var/lib/hydra"

def create_libdir():
    try:
        os.makedirs(LIBDIR)
    except OSError, e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise e

def locate_device(args):
    lla = LocalLustreAudit()
    lla.read_mounts()
    lla.read_fstab()
    device_nodes = lla.get_device_nodes()
    node_result = None
    for d in device_nodes:
        if d['fs_uuid'] == args.uuid:
            node_result = d
    return node_result

def try_run(arg_list):
    p = subprocess.Popen(arg_list, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    stdout, stderr = p.communicate()
    rc = p.wait()
    if rc != 0:
        raise RuntimeError("Error running '%s': '%s' '%s'" % (" ".join(arg_list), stdout, stderr))

    return stdout

def format_target(args):
    from hydra_agent.cmds import lustre

    kwargs = json.loads(args.args)
    cmdline = lustre.mkfs(**kwargs)

    try_run(shlex.split(cmdline))

    blkid_output = try_run(["blkid", "-o", "value", "-s", "UUID", kwargs['device']])

    uuid = blkid_output.strip()

    return {'uuid': uuid}

def register_target(args):
    create_libdir()

    try:
        os.makedirs(args.mountpoint)
    except OSError, e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise e

    try_run(["mount", "-t", "lustre", args.device, args.mountpoint])
    try_run(["umount", args.mountpoint])
    blkid_output = try_run(["blkid", "-o", "value", "-s", "LABEL", args.device])

    return {'label': blkid_output.strip()}

def configure_ha(args):
    if args.primary:
        # now configure pacemaker for this target
        # XXX - crm is a python script -- should look into interfacing
        #       with it directly
        try_run(shlex.split("crm configure primitive %s ocf:hydra:Target meta target-role=\"stopped\" operations \$id=\"%s-operations\" op monitor interval=\"120\" timeout=\"60\" op start interval=\"0\" timeout=\"300\" op stop interval=\"0\" timeout=\"300\" params target=\"%s\"" % (args.label, args.label, args.label)))

    create_libdir()

    try:
        os.makedirs(args.mountpoint)
    except OSError, e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise e

    # Save the metadata for the mount (may throw an IOError)
    file = open("%s/%s" % (LIBDIR, args.label), 'w')
    json.dump({"bdev": args.device, "mntpt": args.mountpoint}, file)
    file.close()

def mount_target(args):
    try:
        file = open("%s/%s" % (LIBDIR, args.label), 'r')
        j = json.load(file)
        file.close()
    except IOError, e:
        raise RuntimeError("Failed to read target data for '%s', is it configured? (%s)" % (args.label, e))

    try_run(['mount', '-t', 'lustre', j['bdev'], j['mntpt']])

def unmount_target(args):
    try:
        file = open("%s/%s" % (LIBDIR, args.label), 'r')
        j = json.load(file)
        file.close()
    except IOError, e:
        raise RuntimeError("Failed to read target data for '%s', is it configured? (%s)" % (args.label, e))

    try_run(["umount", j['bdev']])

def start_target(args):
    try_run(["crm", "resource", "start", args.label])

def stop_target(args):
    try_run(["crm", "resource", "stop", args.label])

def audit(args):
    return LocalLustreAudit().audit_info()
