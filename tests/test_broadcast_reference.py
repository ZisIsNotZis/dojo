"""An ordinary reader can follow a withheld broadcast hit without changing the gate."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class BroadcastReferenceTests(unittest.TestCase):
    def test_follow_hint_to_conditions_not_another_source(self):
        with TemporaryDirectory() as directory:
            db = Path(directory) / "reader's shelf $notes.sqlite3"

            def cli(*args):
                return subprocess.run(
                    [sys.executable, "-B", "-m", "dojo", "--db", str(db), *args],
                    capture_output=True, text=True, check=True,
                )

            cli("add", "--id", "cue-01", "--kind", "experience_claim",
                "--statement", "把还没给出的提示写在固定位置。",
                "--premise", "接班人知道看哪里。",
                "--scope", "两人都在排练厅。",
                "--contradiction", "远程接班看不到纸面。",
                "--source-json", '{"type":"claimed_firsthand","claim":"合成记录","verification":"unverified"}',
                "--session", "rehearsal-a")
            cli("confirm", "cue-01", "--basis", "只标值得检索", "--session", "rehearsal-a")
            query = "-提示 '备注' $HOME"
            broadcast = cli("broadcast", "--session", "reader-b", "--", query)
            verdict = json.loads(broadcast.stdout)
            self.assertEqual(verdict["results"], [])
            self.assertEqual(len(verdict["suppressed"]), 1)
            self.assertEqual(verdict["suppressed"][0]["id"], "cue-01")
            self.assertTrue(verdict["suppressed"][0]["reason"].startswith("single-session provenance:"))
            self.assertIn("不算独立佐证", broadcast.stderr)
            command, = [line.strip() for line in broadcast.stderr.splitlines()
                        if line.lstrip().startswith("python3 -m dojo ")]
            args = shlex.split(command)
            self.assertEqual(args[3:], ["--db", str(db), "search", "--", query])
            opened = subprocess.run(
                [sys.executable, *args[1:]], capture_output=True, text=True, check=True,
                env={**os.environ, "DOJO_DB": str(db.with_name("wrong.sqlite3"))},
            )
            self.assertEqual([row["id"] for row in json.loads(opened.stdout)["results"]], ["cue-01"])
            for words in ("接班人知道看哪里", "两人都在排练厅", "远程接班看不到纸面", "合成记录"):
                self.assertIn(words, opened.stderr)
            # A true vocabulary miss does not claim there was a withheld hit.
            miss = cli("broadcast", "天气预报")
            self.assertEqual(json.loads(miss.stdout)["suppressed"], [])
            self.assertEqual(miss.stderr, "")
            # Following the hint didn't make the record independent or change the exit.
            self.assertEqual(cli("broadcast", "--session", "reader-b", "--", query).stdout,
                             broadcast.stdout)
