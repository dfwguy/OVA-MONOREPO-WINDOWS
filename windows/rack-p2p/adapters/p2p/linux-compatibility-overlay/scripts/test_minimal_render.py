"""Contract checks for interface binding and system/user service rendering."""
import copy
import importlib.util
import json
import pathlib
import unittest

SCRIPT=pathlib.Path(__file__).with_name('render-minimal.py')
SPEC=importlib.util.spec_from_file_location('minimal_renderer',SCRIPT)
RENDERER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


class MinimalRenderTests(unittest.TestCase):
 def test_peer_interfaces_use_server_schema_and_real_fallback_controls(self):
  template=json.loads((SCRIPT.parents[1]/'templates/peer.template.json').read_text())
  template['upload']['ip']='stale-outer-address'
  template['metrics']['ip']='stale-outer-address'
  template['scheduler']['enableBackToSource']=False
  template['health']={'server':{'port':12205}}
  template['stats']={'server':{'port':12206}}
  bound=RENDERER.bind_client_interfaces(copy.deepcopy(template),'192.0.2.14')
  for section in ['upload','proxy','metrics','storage','health','stats']:
   self.assertEqual(bound[section]['server']['ip'],'192.0.2.14')
   self.assertNotIn('ip',bound[section])
  self.assertNotIn('enableBackToSource',bound['scheduler'])
  self.assertTrue(bound['proxy']['disableBackToSource'])
  self.assertTrue(bound['storage']['keep'])

 def test_user_unit_uses_own_session_and_default_target(self):
  cfg={'service_mode':'user','service_user':'REMOTE_USER','service_group':'REMOTE_USER','control_hostname':'example-app'}
  unit=RENDERER.native_unit('seed','/home/REMOTE_USER/kit/dfdaemon',cfg,
   working_directory='/home/REMOTE_USER/kit',after='example-site-p2p-manager.service')
  self.assertNotIn('\nUser=',unit)
  self.assertNotIn('\nGroup=',unit)
  self.assertIn('ConditionHost=example-app',unit)
  self.assertIn('WantedBy=default.target',unit)
  self.assertIn('NoNewPrivileges=true',unit)
  self.assertIn('After=example-site-p2p-manager.service',unit)
  self.assertNotIn('network-online.target',unit)
  self.assertNotIn('LimitNOFILE=',unit)
  self.assertNotIn('docker.service',unit)

 def test_user_units_cannot_be_created_without_an_exact_host_guard(self):
  cfg={'service_mode':'user','service_user':'REMOTE_USER','service_group':'REMOTE_USER'}
  with self.assertRaises(ValueError):RENDERER.native_unit('seed','/home/REMOTE_USER/kit/dfdaemon',cfg)
  cfg['control_hostname']='app-*'
  with self.assertRaises(ValueError):RENDERER.native_unit('seed','/home/REMOTE_USER/kit/dfdaemon',cfg)

 def test_default_system_unit_keeps_explicit_identity_and_target(self):
  cfg={'service_user':'nvis-p2p','service_group':'nvis-p2p'}
  unit=RENDERER.native_unit('manager','/srv/kit/manager',cfg,after='docker.service')
  self.assertIn('\nUser=nvis-p2p\nGroup=nvis-p2p\n',unit)
  self.assertIn('WantedBy=multi-user.target',unit)
  self.assertIn('After=network-online.target docker.service',unit)


if __name__=='__main__':unittest.main()
