"""Check the exact derived fixture cleanup policy without a real socket race."""
import ast
import importlib.util
from pathlib import Path
import types
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_rack_cleanup_builder', HERE / 'build_runtime.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ConnectionClosed(Exception):
    def __init__(self, reason):
        self.reason = reason


class CleanupPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (HERE / 'adapters/rack-status/overlay/windows/test_server.py').read_text()
        source = builder.guard_workflow(source, builder.load(HERE / 'patches/native-tls-test-normal-close.json'))
        tree = ast.parse(source)
        cleanup = next(n for n in ast.walk(tree) if isinstance(n, ast.Try) and len(n.body) == 1 and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Call) and isinstance(n.body[0].value.func, ast.Attribute) and n.body[0].value.func.attr == 'close')
        function = ast.FunctionDef(name='cleanup', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='websocket')], kwonlyargs=[], kw_defaults=[], defaults=[], vararg=None, kwarg=None), body=[cleanup], decorator_list=[], type_params=[])
        namespace = {'ConnectionClosed': ConnectionClosed}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), '<derived-native-fixture-cleanup>', 'exec'), namespace)
        cls.cleanup = staticmethod(namespace['cleanup'])

    def close_with(self, error):
        def close():
            if error is not None:
                raise error
        self.cleanup(types.SimpleNamespace(close=close))

    def test_normal_close_1000_is_accepted_only_during_cleanup(self):
        self.close_with(ConnectionClosed(1000))

    def test_unexpected_close_1006_still_fails(self):
        with self.assertRaises(ConnectionClosed):
            self.close_with(ConnectionClosed(1006))

    def test_unrelated_os_error_still_fails(self):
        with self.assertRaises(OSError):
            self.close_with(OSError('fixture failure'))

    def test_successful_close_is_unchanged(self):
        self.close_with(None)


if __name__ == '__main__':
    unittest.main()
