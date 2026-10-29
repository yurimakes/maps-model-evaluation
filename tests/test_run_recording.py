import json
import tempfile
import unittest
from pathlib import Path
from adapters.record import ROOT,record

class RunRecordingTests(unittest.TestCase):
    def test_repeated_recordings_keep_separate_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)
            args=(ROOT/'configs/experiments/mpnet-phase2.json',ROOT/'results/common/integration-check/normalized_predictions.json',output)
            first=record(*args);second=record(*args)
            self.assertNotEqual(first,second)
            m=json.loads((first/'metrics.json').read_text())
            self.assertEqual(m['questions'],93)
            manifest=json.loads((first/'manifest.json').read_text())
            self.assertFalse(manifest['model_inference_executed'])
            self.assertEqual(manifest['status'],'completed')

    def test_missing_predictions_leave_failed_run_without_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp);predictions=output/'empty.json';predictions.write_text('[]')
            with self.assertRaises(ValueError):
                record(ROOT/'configs/experiments/mpnet-phase2.json',predictions,output/'runs')
            run=next((output/'runs').iterdir())
            self.assertEqual(json.loads((run/'manifest.json').read_text())['status'],'failed')
            self.assertFalse((run/'metrics.json').exists())

if __name__=='__main__':unittest.main()
