"""Validate the distinct native collection interpreter without shell quoting."""
import os
import struct
import sys
if os.name != 'nt' or sys.version_info[:2] != (3, 12) or struct.calcsize('P') != 8:
    raise SystemExit('Collection requires native CPython3.12 x64; the embedded control interpreter is separate.')
print('Native collection prerequisite: CPython ' + sys.version.split()[0] + ' x64')
