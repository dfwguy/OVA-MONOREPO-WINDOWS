"""Render an existing WinSW 2.x wrapper descriptor; never installs/starts services."""
import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def render(runtime, python, winsw, service_id, output):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', service_id):
        raise ValueError('Invalid service identifier.')
    runtime, python, winsw, output = map(lambda p: Path(p).resolve(), (runtime, python, winsw, output))
    if output.exists():
        raise ValueError('Choose a fresh descriptor directory; preserve existing service registration.')
    if not python.is_file() or not winsw.is_file() or not (runtime / 'supervisor.py').is_file():
        raise ValueError('Supply the installed native Python, approved existing WinSW executable and built runtime.')
    output.mkdir(parents=True)
    service = ET.Element('service')
    entries = {'id': service_id, 'name': 'OVA Collection Native Windows',
               'description': 'Native Windows evidence supervisor; read-only configured sources and optional SSH Slurm reads.',
               'executable': str(python), 'arguments': f'-B "{runtime / "supervisor.py"}" --runtime "{runtime}" --config "{runtime / "cluster.json"}"',
               'workingdirectory': str(runtime), 'startmode': 'Automatic', 'stoptimeout': '30sec',
               'stopparentprocessfirst': 'true'}
    for name, value in entries.items():
        ET.SubElement(service, name).text = value
    ET.SubElement(service, 'onfailure', action='restart', delay='10 sec')
    ET.SubElement(service, 'env', name='PYTHONDONTWRITEBYTECODE', value='1')
    ET.SubElement(service, 'env', name='PYTHONUTF8', value='1')
    ET.SubElement(service, 'log', mode='roll-by-size').append(ET.Element('sizeThreshold'))
    service.find('log/sizeThreshold').text = '10240'
    # Use the explicitly supplied existing executable; no third-party download or service mutation.
    import shutil
    shutil.copy2(winsw, output / (service_id + '.exe'))
    xml = output / (service_id + '.xml')
    ET.ElementTree(service).write(xml, encoding='utf-8', xml_declaration=True)
    return xml


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'python', 'winsw', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--service-id', default='OVACollectionNative')
    a = p.parse_args()
    print(render(a.runtime, a.python, a.winsw, a.service_id, a.output))
