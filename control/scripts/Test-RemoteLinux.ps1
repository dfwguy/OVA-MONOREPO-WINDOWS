[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$SshAlias)
$ErrorActionPreference = 'Stop'
if ($SshAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') { throw 'Use a configured OpenSSH alias.' }
$remoteScript = @'
set -eu
printf '=== Identity / OS / CPU ===\n'
id
uname -sm
cat /etc/os-release
getconf GNU_LIBC_VERSION 2>/dev/null || ldd --version 2>/dev/null | head -1 || true
printf '=== Runtime inventory ===\n'
for x in python3 python3.12 bash systemctl docker podman nvidia-smi scontrol sbatch srun enroot nginx node npm curl unzip; do
  command -v "$x" || true
done
python3 --version || true
systemctl --version 2>/dev/null | head -1 || true
printf '=== Storage ===\n'
df -h /var/tmp /opt /var/lib 2>/dev/null || true
printf '=== Listener inventory ===\n'
ss -ltn 2>/dev/null || true
printf 'Pyxis is a Slurm SPANK plugin: confirm its plugin file, plugstack config and scheduler compatibility separately.\n'
'@
# A single SSH connection, read-only commands, no scheduler queries or GPU jobs.
$remoteScript.Replace("`r",'') | & ssh.exe -o BatchMode=yes -o StrictHostKeyChecking=yes $SshAlias 'bash -s'
if ($LASTEXITCODE -ne 0) { throw "Remote preflight failed (exit $LASTEXITCODE)." }
