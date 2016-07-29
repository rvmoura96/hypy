#!/usr/bin/env python3
# coding: utf-8

from winrm import Protocol
from winrm import Response
from base64 import b64encode
from datetime import datetime
from datetime import timedelta
import subprocess
import json
import os.path
import time

vms = None
server = None
config = None
vms_cache_filename = None
states = {3: 'off    ',
          2: 'running',
          9: 'paused ',
          6: 'saved  '}


def connect(index):
    """
    Connect to virtual machine by index using freerdp

    Args:
        index (int): The machine's index generated in the current cache
    """
    load_vms()

    vm_id = vms[index]['Id']
    user = config['user']
    passw = config['pass']
    host = config['host']

    vm_info = get_vm(index)
    if vm_info != '' and vm_info['State'] != 2:
        start_vm(index)
        time.sleep(2)

    cmd = ['xfreerdp', '/v:{0}'.format(host), '/vmconnect:{0}'.format(vm_id), '/u:{0}'.format(user),
           '/p:{0}'.format(passw),
           '/t:{} [{}] {}'.format(host, index, vm_info['Name']), '/cert-ignore']

    # print(cmd)
    subprocess.Popen(cmd)
    # retval = p.wait()


def update_cache(force=False):
    """
    Checks cache file modification time and update vm list
    Creates cache file if nonexistent

    Args:
        force (bool, optional): Whether should force cache update or not

    Returns:
        bool: True for success
    """
    modified = datetime.min
    if os.path.isfile(vms_cache_filename):
        modified = datetime.fromtimestamp(os.path.getmtime(vms_cache_filename))

    if modified < datetime.now() - timedelta(hours=int(config['sync_interval'])) or force:
        ps_script = "Get-VM * | Select Name,Id,State | ConvertTo-Json"
        rs = run_ps(ps_script, server)

        if rs.status_code != 0:
            print(rs.std_err)
            return False

        vms_json = json.loads(rs.std_out.decode('utf-8'))

        # If there is only one vm, make it a list
        if type(vms_json) is dict:
            vms_json = [ vms_json ]

        with open(vms_cache_filename, 'w') as vms_cache_file:
            json.dump(vms_json, vms_cache_file, indent=4)

    return True


def load_vms():
    """
    Loads current cache file into memory

    Returns:
        bool: True for success
    """
    global vms

    try:
        with open(vms_cache_filename, 'r') as vms_cache_file:
            vms = json.load(vms_cache_file)
    except IOError:
        print("Cannot access file {0}".format(vms_cache_filename))
        return False

    return True


def list_vms():
    """
    List virtual machines
    """
    load_vms()

    # Listing
    print("-- Hyper-V Virtual Machine Listing --")
    for vm in vms:
        # print("[{0}] {1} {2} {3}".format(vms.index(vm), states[vm['State']], vm['Name'], vm['Id']))
        print("[{0}] {1} {2}".format(str(vms.index(vm)).rjust(3), states[vm['State']], vm['Name']))


def list_vm_snaps(vm_index):
    """
    List vm snapshots by vm index

    Args:
        vm_index (int): The machine's index generated in the current cache
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = "Get-VM {0} | Get-VMSnapshot | Select Name,ParentSnapshotName | ConvertTo-Json".format(vm_name)

    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    snaps_json = json.loads(rs.std_out.decode('utf-8'))

    # If there is only one snap, make it a list
    if type(snaps_json) is dict:
        snaps_json = [ snaps_json ]

    print("-- Virtual Machine Snapshots --")
    print("{0} {1}".format("Name".ljust(20), "Parent".ljust(20)))
    for snap in snaps_json:
        print("{0} {1}".format(str(snap['Name']).ljust(20), str(snap['ParentSnapshotName']).ljust(20)))


def restore_vm_snap(vm_index, snap_name):
    """
    Restore virtual machine snapshot

    Args:
        vm_index (int): The machine's index generated in the current cache
        snap_name (str): The name of the checkpoint to be restored

    Returns:
        bool: True if success
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = 'Restore-VMSnapshot -Name "{0}" -VMName {1} -Confirm:$false'.format(snap_name, vm_name)

    print('Restoring snapshot "{0}" in {1}'.format(snap_name, vm_name))
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    print("Success")
    return True


def remove_vm_snapshot(vm_index, snap_name, recursive=False):
    """
    Deletes a virtual machine checkpoint

    Args:
        vm_index (int): The machine's index generated in the current cache
        snap_name (str): The name of the checkpoint to be deleted
        recursive (bool, optional): Specifies that the checkpoint’s children are to be
            deleted along with the checkpoint

    Returns:
        bool: True if success
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = 'Remove-VMSnapshot -VMName "{0}" -Name "{1}"'.format(vm_name, snap_name)
    if recursive:
        ps_script += " -IncludeAllChildSnapshots"
    ps_script += " -Confirm:$false"

    print('Removing snapshot "{0}" in "{1}"'.format(snap_name, vm_name))
    if recursive:
        print("and it's children")
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    print("Success")
    return True


def create_vm_snapshot(vm_index, snap_name):
    """
    Create a new snapshot with vm's current state

    Args:
        vm_index (int): The machine's index generated in the current cache
        snap_name (str): The name of the checkpoint to be created

    Returns:
        bool: True if success
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = 'Checkpoint-VM -Name "{0}" -SnapshotName "{1}" -Confirm:$false'.format(vm_name, snap_name)

    print('Creating snapshot "{0}" in "{1}"'.format(snap_name, vm_name))
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    print("Success")
    return True


def get_vm(vm_index):
    """
    Gets vm info by index

    Args:
        vm_index (int): The machine's index generated in the current cache
    """
    load_vms()

    vm_name = vms[vm_index]['Name']

    ps_script = "Get-VM {0} | Select Name,Id,State | ConvertTo-Json".format(vm_name)
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return

    vm_json = json.loads(rs.std_out.decode('utf-8'))
    return vm_json


def stop_vm(vm_index, force=False):
    """
    Stop virtual machine

    Args:
        vm_index (int): The machine's index generated in the current cache
        force (bool): Whether should force shutdown or not
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = "Stop-VM -Name {}".format(vm_name)
    if force:
        ps_script += " -Force"

    print('Stopping VM "{}", force: {}'.format(vm_name, force))
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    print("Success")
    return True


def start_vm(vm_index):
    """
    Start virtual machine

    Args:
        vm_index (int): The machine's index generated in the current cache
    """
    load_vms()

    vm_name = vms[vm_index]['Name']
    ps_script = "Start-VM {0}".format(vm_name)

    print('Starting VM "{0}"'.format(vm_name))
    rs = run_ps(ps_script, server)

    if rs.status_code != 0:
        print(rs.std_err)
        return False

    print("Success")
    return True


def setup(configp):
    """
    Setup hvclient globals and create protocol with server host and credentials

    Args:
        configp (dict): Configuration from config file
    """
    global config
    global server
    global vms_cache_filename

    config = configp

    domain = config['domain']
    user = config['user']
    passw = config['pass']
    host = config['host']
    vms_cache_filename = config['cache_file']

    server = Protocol(endpoint='http://{0}:5985/wsman'.format(host),
                      transport='ntlm',
                      username='{0}\{1}'.format(domain, user),
                      password=passw,
                      server_cert_validation='ignore')


def run_ps(ps, proto):
    """
    Run powershell script on target machine

    Args:
        ps (str): Powershell script to run
        proto (Protocol): Protocol containing target machine

    Returns:
        Response: Object containing stderr, stdout and exit_status
    """
    encoded_ps = b64encode(ps.encode('utf_16_le')).decode('ascii')
    rs = run_cmd('powershell -encodedcommand {0}'.format(encoded_ps), proto)
    return rs


def run_cmd(cmd, proto):
    """
    Run batch script on target machine

    Args:
        cmd (str): batch script to run
        proto (Protocol): Protocol containing target machine

    Returns:
        Response: Object containing stderr, stdout and exit_status
    """
    shell_id = proto.open_shell()
    command_id = proto.run_command(shell_id, cmd)
    rs = Response(proto.get_command_output(shell_id, command_id))
    proto.cleanup_command(shell_id, command_id)
    proto.close_shell(shell_id)
    return rs