"""Ukrainian adaptation: the `uk` language, the UA routing rows and the Ukrainian act grammar."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
if str(PLUGIN_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from memoforge import citations, i18n, quotes, routing, source_text, sources  # noqa: E402

_FILLER = "Суд встановив, що відповідач не виконав зобов'язання у строк. " * 3


def _court_act(number: str = "640/9591/20") -> str:
    body = "\n".join(_FILLER for _ in range(30))
    return (
        "УХВАЛА\n\n05 січня 2026 року\nм. Київ\n\n"
        f"справа №{number}\nадміністративне провадження № Зв/990/61/25\n"
        "Верховний Суд у складі колегії суддів Касаційного адміністративного суду\n\n"
        f"{body}\n\nПОСТАНОВИВ: відмовити."
    )


class UkrainianLanguageTest(unittest.TestCase):
    def test_uk_is_a_language_with_a_pack(self):
        self.assertIn("uk", i18n.LANGUAGES)
        self.assertEqual("uk", i18n.load("uk")["code"])

    def test_risk_line_and_months_are_ukrainian(self):
        self.assertEqual("Ризик", i18n.load("uk")["memo"]["risk"]["label"])
        self.assertEqual("січня", i18n.load("uk")["memo"]["months"][0])

    def test_detect_lang_tells_ukrainian_from_russian(self):
        self.assertEqual("uk", quotes.detect_lang("Загальна позовна давність встановлюється у три роки, їх"))
        self.assertEqual("ru", quotes.detect_lang("Общий срок исковой давности составляет три года"))
        self.assertEqual("en", quotes.detect_lang("The general limitation period is three years"))

    def test_ukrainian_letters_survive_the_slug(self):
        self.assertEqual("yi", sources.transliterate("ї"))


class UkrainianRoutingTest(unittest.TestCase):
    def test_ukraine_routes_to_ldh_in_every_layer(self):
        for layer in routing.LAYERS:
            with self.subTest(layer=layer):
                row = routing.route(layer, "Ukraine")
                self.assertEqual("UA", row["jurisdiction"])
                self.assertTrue(row["known"])
                self.assertIn("ldh_search", row["tools"])
                self.assertTrue(row["ldh_sources"])
                self.assertTrue(all(source.startswith("UA/") for source in row["ldh_sources"]))

    def test_no_russian_row_is_left(self):
        for layer in routing.LAYERS:
            self.assertFalse(routing.route(layer, "RU")["known"])


class UkrainianSourceTextTest(unittest.TestCase):
    def test_a_ukrainian_court_act_is_not_read_as_a_russian_one(self):
        self.assertFalse(source_text.is_russian_act(_court_act()))

    def test_a_court_act_with_its_number_in_the_header_is_full_text(self):
        call = source_text.verdict(_court_act(), layer="case_law", expect_number="640/9591/20")
        self.assertEqual("full_text", call["outcome"])

    def test_another_case_number_leaves_the_act_an_excerpt(self):
        call = source_text.verdict(_court_act(), layer="case_law", expect_number="640/9591/21")
        self.assertEqual("excerpt:identity_unverified", call["outcome"])

    def test_article_heading_stands_in_ukrainian(self):
        filler = "Текст норми для довжини. " * 20
        law = (
            "ЦИВІЛЬНИЙ КОДЕКС УКРАЇНИ\n\n"
            "Стаття 256. Поняття позовної давності\n\n1. Позовна давність - це строк.\n\n"
            "Стаття 257. Загальна позовна давність\n\n"
            f"1. Загальна позовна давність встановлюється тривалістю у три роки. {filler}\n\n"
            "Стаття 258. Спеціальна позовна давність\n\n1. Для окремих видів.\n"
        )
        self.assertEqual("full_text", source_text.verdict(law, layer="statutes", expect_article="257")["outcome"])
        self.assertEqual(
            "excerpt:article_not_found", source_text.verdict(law, layer="statutes", expect_article="999")["outcome"]
        )

    def test_both_copies_of_the_heading_grammar_match(self):
        self.assertEqual(sources.ARTICLE_HEADING_PREFIX, source_text.ARTICLE_HEADING_PREFIX)
        self.assertIn("Стаття", sources.ARTICLE_HEADING_PREFIX)


class UkrainianPinpointTest(unittest.TestCase):
    def test_ukrainian_pinpoint_labels_are_accepted(self):
        for pinpoint in ("ст. 257", "п. 2 ч. 1 ст. 257", "абз. 2 ч. 1 ст. 257", "п. 3 розд. «Відшкодування»", "дод. 2"):
            with self.subTest(pinpoint=pinpoint):
                self.assertTrue(citations.CYRILLIC_PINPOINT.match(pinpoint))


if __name__ == "__main__":
    unittest.main()
