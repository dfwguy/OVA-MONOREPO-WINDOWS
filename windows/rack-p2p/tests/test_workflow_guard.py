"""Exercise the existing workflow scheduler boundary without importing startup state."""
import ast
import importlib.util
import logging
import os
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_rack_builder', HERE / 'build_runtime.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
ORIGINAL = (HERE / 'adapters/rack-status/overlay/backend/workflow_engine.py').read_text(encoding='utf-8')
GUARD = builder.load(HERE / 'patches/pythoncm-workflow-guard.json')


class WorkflowGuardTest(unittest.TestCase):
    def execute_boundary(self, source, kind):
        function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_execute_scheduler_step')
        scheduler = types.SimpleNamespace(kind=kind, submissions=[])
        def submit(job):
            scheduler.submissions.append(vars(job))
            return types.SimpleNamespace(job_id='fixture-id')
        scheduler.submit = submit
        scheduler.wait = lambda *_a, **_kw: types.SimpleNamespace(stdout='fixture output', stderr='', returncode=0, state='COMPLETED', job_id='fixture-id')
        module = types.ModuleType('schedulers')
        module.JobSpec = lambda **kwargs: types.SimpleNamespace(**kwargs)
        module.build_scheduler = lambda *_a, **_kw: scheduler
        saved = []
        namespace = {'os': os, 're': re, 'script_tree': types.SimpleNamespace(script_env=lambda: {'NVIS_SCRIPTS_DIR': '/approved/scripts'}), '_scripts_dir': lambda: '/approved/scripts', '_resolve_step_connection': lambda _step: (None, 'control'), '_logger': logging.getLogger('workflow-guard-test'), '_save_step_output': lambda *_args: saved.append(_args), '_apply_evaluation': lambda _run, _step, code, _stdout, _stderr, out: (code == 0, out)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<existing-workflow-boundary>', 'exec'), namespace)
        with patch.dict(sys.modules, {'schedulers': module}):
            result = namespace['_execute_scheduler_step']({'run_id': 'fixture-run', 'params': {}}, {'id': 'fixture-step', 'scheduler': {'kind': kind, 'command': 'printf fixture', 'timeout': 30}})
        return result, scheduler.submissions

    def test_pythoncm_refuses_before_submit(self):
        result, submissions = self.execute_boundary(builder.guard_workflow(ORIGINAL, GUARD), 'pythoncm')
        self.assertFalse(result[0])
        self.assertIn('PythonCM workflow execution is disabled', result[1])
        self.assertEqual([], submissions)

    def test_slurm_boundary_is_unchanged(self):
        original_result, original_submissions = self.execute_boundary(ORIGINAL, 'slurm')
        patched_result, patched_submissions = self.execute_boundary(builder.guard_workflow(ORIGINAL, GUARD), 'slurm')
        self.assertTrue(patched_result[0])
        self.assertEqual(original_result, patched_result)
        self.assertEqual(original_submissions, patched_submissions)
        self.assertEqual(1, len(patched_submissions))

    def test_changed_preimage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'preimage mismatch'):
            builder.guard_workflow(ORIGINAL + '\n# modified input\n', GUARD)


if __name__ == '__main__':
    unittest.main()
