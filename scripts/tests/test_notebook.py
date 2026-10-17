"""The user's NotebookLM notebook: the option, the researcher dispatch value and the rules it carries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402

from _pipeline import temp_root  # noqa: E402
from memoforge import dispatch, machine, modes, state_io, task  # noqa: E402

import test_dispatch  # noqa: E402

OPTION = "notebooklm_notebook"
TOOL_SUFFIXES = (
    "notebook_list",
    "source_list_drive",
    "notebook_query",
    "notebook_query_start",
    "notebook_query_status",
    "source_get_content",
)


def _researcher_spec(test: unittest.TestCase, notebook: str | None) -> dict:
    root = temp_root(test)
    work_dir = root / test_dispatch.TASK_ID
    work_dir.mkdir(parents=True, exist_ok=True)
    state = test_dispatch._state(work_dir)
    if notebook is not None:
        state["config"][OPTION] = notebook
    state_io.write_json_atomic(
        work_dir / "plan.json",
        {
            "classification": "regulatory_analysis",
            "jurisdictions": ["UA"],
            "doctrine_required": True,
            "estimated_complexity": "high",
            "issues": [
                {"issue_id": "i1", "title": "Строк", "question": "Який строк?", "jurisdictions": ["UA"]}
            ],
        },
    )
    specs = machine.researcher_specs(work_dir, state, ["statutes"])
    return {"work_dir": work_dir, "state": state, "spec": specs[0]}


class NotebookOptionTest(unittest.TestCase):
    def test_the_option_is_declared_everywhere_it_is_read(self):
        self.assertIn(OPTION, task.OPTION_KEYS)
        self.assertEqual(task.OPTION_DEFAULTS[OPTION], "")
        manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn(OPTION, manifest["userConfig"])
        schema = json.loads((PLUGIN_ROOT / "schemas" / "state.schema.json").read_text(encoding="utf-8"))
        self.assertIn(OPTION, schema["$defs"]["config"]["properties"])

    def test_a_title_is_a_valid_value_and_an_empty_one_is_not(self):
        self.assertIsNone(task.validate_option(OPTION, "Практика ВС: оренда землі"))
        self.assertIsNotNone(task.validate_option(OPTION, "  "))

    def test_the_value_reaches_state_config(self):
        config = modes.resolve_config("full", {OPTION: "Мій блокнот"})
        self.assertEqual(config[OPTION], "Мій блокнот")
        self.assertIsNone(modes.resolve_config("full", {})[OPTION])

    def test_a_per_task_flag_beats_the_default(self):
        flags, errors = task.parse_option_flags([f"{OPTION}=Блокнот про оренду"])
        self.assertEqual(errors, [])
        self.assertEqual(task.resolve_options(flags)["values"][OPTION], "Блокнот про оренду")
        self.assertNotIn(OPTION, task.resolve_options({})["values"])


class NotebookDispatchTest(unittest.TestCase):
    def test_no_notebook_means_none(self):
        built = _researcher_spec(self, None)
        self.assertEqual(built["spec"]["extra"]["user_notebook"], "none")

    def test_the_notebook_travels_to_the_researcher_prompt(self):
        built = _researcher_spec(self, "Практика ВС: оренда землі")
        self.assertEqual(built["spec"]["extra"]["user_notebook"], "Практика ВС: оренда землі")
        rendered = dispatch.render_agents(
            built["work_dir"],
            built["state"],
            step_id="s-042",
            attempt=1,
            specs=[built["spec"]],
            position=5,
            total=13,
        )
        self.assertIn("Практика ВС: оренда землі", rendered[0]["prompt"])

    def test_every_template_value_has_a_default(self):
        self.assertEqual(dispatch._DEFAULT_EXTRAS["user_notebook"], "none")


class NotebookRulesTest(unittest.TestCase):
    """The text the researcher follows: what it may call, register and never register."""

    def setUp(self):
        self.prompt = (PLUGIN_ROOT / "scripts" / "memoforge" / "prompts" / "legal-researcher.md").read_text(
            encoding="utf-8"
        )
        self.agent = (PLUGIN_ROOT / "agents" / "legal-researcher.md").read_text(encoding="utf-8")

    def test_the_prompt_names_the_four_tools_by_suffix(self):
        for suffix in TOOL_SUFFIXES:
            self.assertIn(suffix, self.prompt)

    def test_text_is_registered_as_the_clients_file_from_source_content(self):
        self.assertIn("--raw-kind client_file --tool notebooklm_source_get_content", self.prompt)

    def test_a_query_answer_is_never_a_source(self):
        self.assertIn("never registered, quoted or cited as source text", self.prompt)

    def test_the_section_is_inactive_without_a_notebook(self):
        self.assertIn("Applies only when the `notebook` parameter above is not `none`", self.prompt)

    def test_the_agent_definition_points_at_the_section(self):
        self.assertIn('section "The user\'s notebook"', self.agent)

    def test_the_prompt_sends_the_researcher_to_the_protocol_file(self):
        self.assertIn("${paths_agent_core}/notebooklm.md", self.prompt)
        self.assertTrue((PLUGIN_ROOT / "lib" / "agent-core" / "notebooklm.md").is_file())

    def test_citation_fragments_are_registered_as_an_excerpt(self):
        self.assertIn("--raw-kind excerpt --tool notebooklm_notebook_query", self.prompt)

    def test_the_prompt_keeps_the_notebook_read_only(self):
        self.assertIn("no tool that adds, renames, shares or deletes anything in the notebook is called", self.prompt)



class NotebookProtocolTest(unittest.TestCase):
    """The user's field-tested rules survive in the file the researcher reads."""

    def setUp(self):
        self.text = (PLUGIN_ROOT / "lib" / "agent-core" / "notebooklm.md").read_text(encoding="utf-8")

    def test_sources_are_listed_before_the_first_question(self):
        self.assertIn("`source_list_drive`", self.text)
        self.assertIn("before any substantive question", self.text)

    def test_one_question_one_query_and_no_bigger_timeout(self):
        self.assertIn("One question, one `notebook_query`", self.text)
        self.assertIn("a larger `timeout` does not help", self.text)

    def test_parallel_narrow_queries_each_start_a_new_conversation(self):
        self.assertIn("`new_conversation: true`", self.text)
        self.assertIn("`source_ids`", self.text)

    def test_only_cited_text_is_verbatim(self):
        self.assertIn("Only the citation field, `cited_text`, is verbatim", self.text)

    def test_an_absence_claim_needs_a_gap_free_chain_of_citations(self):
        self.assertIn("a gap between neighbouring citations is an uncovered zone", self.text)
        self.assertIn("ПОВНІСТЮ і дослівно", self.text)
        self.assertIn("`confidence: low`", self.text)

    def test_a_missing_source_is_named_and_never_added_by_the_pipeline(self):
        self.assertIn("never adds a source to it", self.text)

    def test_an_expired_login_is_reported_and_not_replaced_by_the_web(self):
        self.assertIn("`nlm login`", self.text)
        self.assertIn("nothing they return is presented as the notebook's answer", self.text)


if __name__ == "__main__":
    unittest.main()
