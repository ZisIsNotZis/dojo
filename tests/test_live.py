"""The shipped model default must be a name the endpoint can answer.

The defect this guards is `dojo/live.py`'s `DEFAULT_MODEL` being spelled
`github-copilot/gpt-6-luna`: the local LiteLLM endpoint publishes
`github_copilot/gpt-6-luna`, so a user who sets no `DOJO_LLM_MODEL` got HTTP 400
on every request. A default that always fails is a defect, not a configuration,
so the default is pinned here and any module that spells it another way fails.
"""

import re
import unittest
from pathlib import Path

from dojo.live import DEFAULT_MODEL, LiveConfig

LIVE_URL = "http://127.0.0.1:4000/v1"
PUBLISHED_MODEL = "github_copilot/gpt-6-luna"
PACKAGE_DIR = Path(__file__).resolve().parent.parent / "dojo"
# Modules that build a request to the OpenAI-compatible endpoint. `compare.py`
# and `demo.py` are excluded on purpose: they name the pi-side provider and
# reproduce a frozen packet, neither of which is an HTTP model id.
HTTP_MODEL_MODULES = ("live.py", "discuss.py")


class DefaultModelTests(unittest.TestCase):
    def test_default_matches_the_published_model_id(self) -> None:
        self.assertEqual(DEFAULT_MODEL, PUBLISHED_MODEL)

    def test_config_without_model_env_uses_the_default(self) -> None:
        config = LiveConfig.from_environment({"DOJO_LLM_BASE_URL": LIVE_URL})
        self.assertEqual(config.model, PUBLISHED_MODEL)

    def test_explicit_model_env_still_wins(self) -> None:
        config = LiveConfig.from_environment({"DOJO_LLM_BASE_URL": LIVE_URL, "DOJO_LLM_MODEL": "other/model"})
        self.assertEqual(config.model, "other/model")

    def test_no_http_module_spells_the_model_with_a_hyphen_provider(self) -> None:
        offenders = []
        for name in HTTP_MODEL_MODULES:
            path = PACKAGE_DIR / name
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"github[-_]copilot/gpt-6-luna", text):
                if match.group(0) != PUBLISHED_MODEL:
                    offenders.append(f"{name}: {match.group(0)}")
        self.assertEqual(offenders, [], "an HTTP model id must use the endpoint's underscore spelling")


if __name__ == "__main__":
    unittest.main()
