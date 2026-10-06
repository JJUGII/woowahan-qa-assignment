"""Report regression checks: failures, skips and missing runs must not become passes."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from run_python_tests import DetailedResult, InventoryReport
from test_report import write_report


class ReportChecks(unittest.TestCase):
    def execute(self, cls):
        with contextlib.redirect_stdout(io.StringIO()):
            return unittest.TextTestRunner(stream=io.StringIO(),resultclass=DetailedResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(cls))

    def test_failure_and_teardown_error(self):
        class Failure(unittest.TestCase):
            def test_x(self): self.fail('assert evidence')
        class Teardown(unittest.TestCase):
            def test_x(self): pass
            def tearDown(self): raise RuntimeError('cleanup evidence')
        for cls,status in [(Failure,'FAIL'),(Teardown,'ERROR')]:
            result=self.execute(cls)
            self.assertFalse(result.wasSuccessful());self.assertEqual(result.rows[0]['status'],status)

    def test_class_setup_error_is_reported(self):
        class Broken(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise RuntimeError('setup evidence')
            def test_x(self): pass
        result=self.execute(Broken)
        self.assertEqual(result.rows[0]['status'],'ERROR')
        self.assertIn('setup evidence',result.rows[0]['actual'])

    def test_class_skip_is_not_pass(self):
        class Skipped(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise unittest.SkipTest('not prepared')
            def test_x(self): pass
        result=self.execute(Skipped)
        self.assertEqual(result.rows[0]['status'],'SKIP')

    def test_subtest_failure_is_reported(self):
        class Sub(unittest.TestCase):
            def test_x(self):
                for number in [1,2]:
                    with self.subTest(number=number): self.assertEqual(number,1)
        result=self.execute(Sub)
        self.assertEqual(result.rows[0]['status'],'FAIL')
        self.assertIn('number=2',result.rows[0]['actual'])

    def test_pytest_teardown_failure_overrides_call_pass(self):
        plugin=InventoryReport.__new__(InventoryReport)
        plugin.items={'test_x':{'TC ID':'ID','Title':'Title','Precondition':'','Procedure':'','Result':''}}
        plugin.phases={'test_x':[SimpleNamespace(when=phase,failed=failed,passed=not failed,skipped=False,
            longrepr='cleanup failed',duration=.1,user_properties=[],sections=[]) for phase,failed in [('call',False),('teardown',True)]]}
        self.assertEqual(plugin.row('test_x')['status'],'ERROR')

    def test_report_escaping_and_incomplete_status(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            data=write_report(directory,'Title','Scope',[dict(id='TC',title='<script>alert(1)</script>',status='NOT_RUN',actual='<b>')])
            self.assertEqual(data['overall'],'INCOMPLETE')
            text=(Path(directory)/'시험성적서.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)</script>',text)
            self.assertIn('&lt;script&gt;',text)

if __name__=='__main__': unittest.main()
