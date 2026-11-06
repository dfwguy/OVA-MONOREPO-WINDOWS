"""Read-only Slurm queries over native OpenSSH; no local Linux runtime."""
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
from native_durable import atomic_write


def command(arguments, timeout, config):
    args = [str(value) for value in arguments]
    executable = PurePosixPath(args[0].replace('\\', '/')).name
    if executable in ('scontrol', 'sacct'):
        if not config.get('native_scheduler_enabled', False):
            raise RuntimeError('Scheduler queries are disabled; this configuration accepts local mirrored evidence only.')
        alias = config.get('scheduler_ssh_alias', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', alias):
            raise ValueError('Configure an approved scheduler SSH alias.')
        output_file = None
        if executable == 'scontrol':
            if args[1:4] == ['show', 'jobs', '-o'] and len(args) == 4:
                pass
            elif args[1:3] == ['show', 'hostnames'] and len(args) == 4:
                pass
            elif args[1:3] == ['write', 'batch_script'] and len(args) == 5 and args[3].isdecimal():
                output_file = Path(args[4])
                args[-1] = '-'
            else:
                raise ValueError('Unsupported scheduler command; mutations are not allowed.')
        elif not (len(args) == 7 and args[1:3] == ['--json', '--allusers'] and args[3] == '--starttime' and args[5] == '--endtime'):
            raise ValueError('Only bounded JSON accounting reads are allowed.')
        binary_directory = config.get('scheduler_remote_bin', '/usr/bin')
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', binary_directory):
            raise ValueError('Invalid approved remote Slurm binary directory.')
        args[0] = binary_directory.rstrip('/') + '/' + executable
        from settings import ssh_args
        ssh = ssh_args(alias)
        ssh[0] = config.get('ssh_executable', 'ssh.exe' if os.name == 'nt' else 'ssh')
        args = ssh + ['env TZ=UTC ' + shlex.join(args)]
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True).stdout
        if output_file is not None:
            atomic_write(output_file, result)
            return b''
        return result
    if executable in ('ssh', 'ssh.exe'):
        args[0] = config.get('ssh_executable', 'ssh.exe' if os.name == 'nt' else 'ssh')
        return subprocess.run(args, capture_output=True, timeout=timeout, check=True).stdout
    raise ValueError('Only explicit read-only Slurm or SSH transports are supported.')
