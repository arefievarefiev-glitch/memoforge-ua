"""Static source-routing table and the MCP call estimate (ТЗ §4.3; no new HTTP clients here)."""

from __future__ import annotations

import json
from pathlib import Path

from . import limits, pylauncher

LAYERS: tuple[str, ...] = ("statutes", "case_law", "doctrine")

DISCOVER_CACHE_PATH = "lib/routing/discover-cache.json"
"""Cached LDH source names; refreshed by hand, never at runtime (analysis/05 §5)."""

# --- MCP server aliases (§4.3) --------------------------------------------

MCP_SERVERS: dict[str, str] = {
    "ldh": "legal-data-hunter",
    "courtlistener": "courtlistener",
    "legalviz": "legalviz",
    "uklegal": "uk-legal",
    "justicelibre": "justicelibre",
    "opencaselaw": "opencaselaw",
    "fedregs": "federal-regulations",
    "lex": "lex",
    "casus": "casus",
    "fas": "fas-search",
}
"""Routing alias -> bundled server of `.mcp.json`, and the key of that server in `intake/mcp-probe.json`.

A tool named `<alias>_<suffix>` in the table below is that server's `<suffix>` tool, whatever
namespace the host puts it under: `mcp__plugin_memoforge_<server>__<suffix>` in Claude Code, an
opaque connector namespace in Cowork. The probe records the namespaces it found and the agent
matches them by tool suffix; the plan gate reads the same aliases out of a routing row to see
whether that row still has a legal database behind it (§4.3, `gates.sources_question_needed`).
"""

MCP_SERVER_LABELS: dict[str, str] = {
    "ldh": "Legal Data Hunter",
    "courtlistener": "CourtListener",
    "legalviz": "LegalViz",
    "uklegal": "UK Legal",
    "justicelibre": "JusticeLibre (FR)",
    "opencaselaw": "OpenCaseLaw (CH)",
    "fedregs": "Federal Regulations (US)",
    "lex": "Lex (UK, i.AI)",
    "casus": "CasusLegal (RU)",
    "fas": "FAS advertising practice (RU)",
}
"""How a server is named to the user — in the `Sources` question of the plan gate (§2.4)."""

MANIFEST_PATH = ".mcp.json"
"""`<plugin_root>/.mcp.json` — the one place that says which URL each bundled server answers on."""


def manifest_host(url: object) -> str:
    """Lower-case host of a manifest URL; `""` when there is none (D-192)."""
    text = str(url or "").strip()
    scheme, separator, rest = text.partition("://")
    if not separator:
        return ""
    return rest.split("/")[0].split("?")[0].rsplit("@", 1)[-1].split(":")[0].lower()


def manifest_hosts() -> dict[str, str]:
    """`{host: server key}` of `.mcp.json`; empty when the manifest cannot be read (D-192).

    Read on demand rather than cached: the file is tiny, and the only callers are the annex note
    and the classification test, neither of which runs in a loop.
    """
    path = pylauncher.plugin_root() / MANIFEST_PATH
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    servers = manifest.get("mcpServers") if isinstance(manifest, dict) else None
    hosts: dict[str, str] = {}
    for name, server in (servers or {}).items():
        host = manifest_host(server.get("url") if isinstance(server, dict) else "")
        if host:
            hosts[host] = str(name)
    return hosts


def server_label(host: object) -> str:
    """The label of the bundled server answering on `host`, or `""` for any other host (D-192).

    `.mcp.json` maps the host to the server key, `MCP_SERVERS` that key back to a routing alias and
    `MCP_SERVER_LABELS` the alias to the words the user already reads at the plan gate.
    """
    name = manifest_hosts().get(str(host or "").strip().lower())
    if not name:
        return ""
    for alias, server in MCP_SERVERS.items():
        if server == name:
            return MCP_SERVER_LABELS.get(alias, "")
    return ""

SPECIALIST_SERVERS: tuple[str, ...] = ("fas",)
"""D-184a: a specialist server answers one subject area only and never counts as coverage of a row.

FAS holds advertising, unfair-competition and antimonopoly decisions alone, so a Russian case-law
question outside those subjects is unserved even with `fas` connected. `row_servers` keeps naming
it — budgets, the intake digest and the researcher's routing block still route to it — and only
`gates.coverage_gaps` drops it, so «FAS is up» never silences the `Sources` question (§2.4).
"""


def row_servers(layer: str, jurisdiction: object) -> list[str]:
    """The bundled servers one routing row can use, in tool order and without repeats (§4.3).

    A row whose tools are only `WebFetch`/`WebSearch` answers with an empty list: it never had a
    legal database behind it, so no probe result can take one away from it.
    """
    aliases: list[str] = []
    for tool in route(layer, jurisdiction)["tools"]:
        alias = tool.split("_", 1)[0]
        if alias in MCP_SERVERS and alias not in aliases:
            aliases.append(alias)
    return aliases


DIGEST_HOME: tuple[str, ...] = ("UA",)
"""Jurisdictions that head every layer of the intake digest ahead of `ROUTING`'s own rows."""

DIGEST_LAYERS: tuple[str, ...] = ("statutes", "case_law")
"""Layers the intake digest covers (D-110); `doctrine` is WebSearch-first and needs no tool order."""


def routing_digest(connected: dict, exhausted: object = ()) -> str:
    """Tool order per `layer × jurisdiction`, filtered to the connected servers (§4.3, D-110).

    `connected` is the `namespaces` object of `intake/mcp-probe.json`: an alias with a truthy
    namespace is reachable in this session, everything else is not. A tool of an unreachable server
    is dropped from its line, the Web fallbacks always stay (with the row's preferred domain), so
    every line ends with something the analyst can actually call. Eight lines — two layers × Ukraine
    (the home jurisdiction of this fork, a row of `EXTRA_JURISDICTION_ROWS`) and the three
    jurisdictions of `ROUTING`.

    `exhausted` is the set of aliases whose provider quota is spent for today (D-122): connected or
    not, their tools leave every line, so nobody is sent back to a server that already said no.
    """
    namespaces = connected if isinstance(connected, dict) else {}
    spent = {str(alias) for alias in (exhausted or ())}
    lines: list[str] = []
    for layer in DIGEST_LAYERS:
        for code in (*DIGEST_HOME, *ROUTING[layer]):
            row = route(layer, code)
            tools: list[str] = []
            for tool in row["tools"]:
                alias = tool.split("_", 1)[0]
                if alias in MCP_SERVERS:
                    if namespaces.get(alias) and alias not in spent:
                        tools.append(tool)
                elif tool == "WebFetch" and row["domains"]:
                    tools.append(f"WebFetch {row['domains'][0]}")
                else:
                    tools.append(tool)
            lines.append(f"{code} {layer}: " + (" → ".join(tools) or "WebSearch"))
    return "\n".join(lines)


# --- jurisdiction codes ---------------------------------------------------

JURISDICTION_ALIASES: dict[str, str] = {
    "UKR": "UA",
    "UKRAINE": "UA",
    "УКРАЇНА": "UA",
    "УКРАИНА": "UA",
    "GB": "UK",
    "GBR": "UK",
    "UNITED KINGDOM": "UK",
    "GREAT BRITAIN": "UK",
    "EN": "UK",
    "USA": "US",
    "UNITED STATES": "US",
    "EEA": "EU",
    "EEA MEMBER STATES": "EU",
    "EEA STATES": "EU",
    "MEMBER STATES": "EU",
    "EUROPEAN UNION": "EU",
}
"""`GB` is empty in LDH `discover_sources`; the working code is `UK` (§4.3, analysis/05 §5).

The three collective spellings resolve to `EU` so that a plan saying «EEA member states» gets the
EU row rather than the empty default row it used to get; `route()` marks that answer
`member_state_generic`, because the EU row carries Union law only — the national implementing law
behind it needs the concrete ISO codes of `MEMBER_STATES`.
"""

MEMBER_STATE_GENERIC: frozenset = frozenset({"EEA MEMBER STATES", "EEA STATES", "MEMBER STATES"})
"""Spellings that name a group of states instead of one; flagged in the `route()` answer."""


def _upper(code: object) -> str:
    """Trimmed upper-case spelling with `_` read as a space (`eea_member_states`)."""
    return str(code or "").strip().upper().replace("_", " ")


def normalize_jurisdiction(code: object) -> str:
    """Upper-case ISO-ish code with the §4.3 aliases applied (`GB` -> `UK`)."""
    upper = _upper(code)
    if not upper:
        return ""
    return JURISDICTION_ALIASES.get(upper, upper)


# --- layer rules (§4.3 table; only the agent's own row reaches its prompt) -

LAYER_RULES: dict[str, dict] = {
    "statutes": {
        "websearch_primary": False,
        "websearch_note": "discovery only",
        "citable": "MCP documents; WebFetch of issuing-body portals",
    },
    "case_law": {
        "websearch_primary": False,
        "websearch_note": "discovery only",
        "citable": "MCP documents; official courts / Find Case Law / CourtListener",
    },
    "doctrine": {
        "websearch_primary": True,
        "websearch_note": "primary discovery tool",
        "citable": (
            "MCP documents; official regulatory guidance, peer-reviewed publications, "
            "SSRN-class repositories"
        ),
    },
}


def layer_rules(layer: str) -> dict:
    """One row of the §4.3 layer table (the `${layer_rules}` placeholder of the dispatch prompt)."""
    try:
        return dict(LAYER_RULES[layer])
    except KeyError as exc:
        raise ValueError(f"unknown_layer: {layer!r}") from exc


# --- routing table (§4.3) -------------------------------------------------

_DEFAULT_ROWS: dict[str, dict] = {
    "statutes": {
        "tools": ["ldh_resolve_reference", "ldh_search", "WebFetch"],
        "domains": [],
        "note": "Resolve the reference first, then fetch only the pinpointed part; never the full act.",
    },
    "case_law": {
        "tools": ["ldh_search", "WebFetch"],
        "domains": [],
        "note": "Official court portals only.",
    },
    "doctrine": {
        "tools": ["WebSearch", "ldh_search", "WebFetch"],
        "domains": [],
        "note": "Regulatory guidance and peer-reviewed publications; WebSearch is primary.",
    },
}

ROUTING: dict[str, dict[str, dict]] = {
    "statutes": {
        "EU": {
            "tools": [
                "legalviz_resolve",
                "legalviz_get_law_part",
                "ldh_resolve_reference",
                "ldh_search",
                "WebFetch",
            ],
            "ldh_sources": ["EU/EUR-Lex", "EU/ConsolidatedLegislation"],
            "domains": ["publications.europa.eu", "eur-lex.europa.eu"],
            "note": (
                "legalviz_resolve (or legalviz_search_eu_law when only a title or keyword is known) "
                "turns the reference into a CELEX id, then legalviz_get_law_part with part=structure "
                "for the table of contents and one more call for the pinpointed article, version=<date> "
                "for a point-in-time reading; never pull a whole act, take get_law_part slices. "
                "legalviz_get_law_part with version=\"current\" also reports the consolidated CELEX it "
                "read in versionCelex — for the AI Act that is 02024R1689-20260727, as amended by "
                "Regulation (EU) 2026/1744 (Digital Omnibus on AI, CELEX 32026R1744). If LegalViz is "
                "unavailable, ldh_resolve_reference with hint_country=EU and a minimal result_detail "
                "for metadata and status, then the article text via ldh_search with a pinpoint or a "
                "WebFetch of Cellar, https://publications.europa.eu/resource/celex/<CELEX>, sent with "
                "Accept: application/xhtml+xml and Accept-Language: eng — without that Accept header "
                "Cellar answers with 60 MB of RDF, and with text/html it answers 404. The pinpoint "
                "anchors id=\"art_N\" exist only on the consolidated CELEX 0YYYYRNNNN-YYYYMMDD, not on "
                "the OJ form. eur-lex.europa.eu is the fallback behind Cellar: when it answers HTTP 202 "
                "with x-amzn-waf-action: challenge, retrying is useless — switch to Cellar or LegalViz."
            ),
        },
        "UK": {
            "tools": [
                "uklegal_legislation_search",
                "uklegal_legislation_get_toc",
                "uklegal_legislation_get_section",
                "lex_search_for_legislation_sections",
                "lex_lookup_legislation",
                "lex_get_legislation_sections",
                "lex_get_explanatory_note_by_section",
                "lex_search_amendments",
                "WebFetch",
                "ldh_search",
            ],
            "ldh_sources": ["UK/Legislation"],
            "domains": ["legislation.gov.uk"],
            "note": (
                "uklegal_legislation_search finds the act, uklegal_legislation_get_toc its "
                "structure, uklegal_legislation_get_section the parsed text of the one section you "
                "need — that answer carries extent and in-force metadata, so it is also the currency "
                "check for UK legislation. uklegal_citations_resolve confirms a citation points at a "
                "real document and uklegal_citations_format_oscola formats it. "
                "lex_* is the i.AI (GDS) service over the same legislation.gov.uk data: "
                "lex_lookup_legislation takes the official citation (ukpga/2018/12), "
                "lex_get_legislation_sections and lex_search_for_legislation_sections read or find "
                "sections, lex_get_explanatory_note_by_section adds the explanatory note of a "
                "section and lex_search_amendments the amendments that touched it — use it for "
                "explanatory notes and amendment history, or when uklegal is down; its case law is "
                "disabled, so judgments stay on uklegal. Fall back to a "
                "WebFetch of legislation.gov.uk, which is authoritative and point-in-time addressable. "
                "The source is one provision, saved by code from its legislation.gov.uk page with the "
                "act's short name in --meta (D-218): `mf sources save --workdir <work_dir> --layer statutes "
                "--title \"UK GDPR, Article 82\" --citation \"UK GDPR, art 82\" --tier critical "
                "--url https://www.legislation.gov.uk/eur/2016/679/article/82 --expect-article 82 "
                "--meta '{\"short_name\": \"UK GDPR\"}'`."
            ),
        },
        "US": {
            "tools": [
                "fedregs_regulations_get_cfr_section",
                "fedregs_regulations_browse_cfr",
                "fedregs_regulations_search_rules",
                "fedregs_regulations_get_document",
                "WebFetch",
                "ldh_search",
            ],
            "ldh_sources": ["US/USCode"],
            "domains": ["govinfo.gov"],
            "note": (
                "Two federal sources, two routes. Statutes (U.S. Code): govinfo.gov only, and there the "
                "year-free form govinfo.gov/link/uscode/<title>/<section>?link-type=html is preferred: "
                "it redirects to the current edition by itself. Regulations (CFR) and rulemaking: "
                "fedregs_regulations_get_cfr_section with title, part and section (16, 312, 312.3) "
                "returns the codified text as of a date; register it with --tool "
                "fedregs_regulations_get_cfr_section and the official page as --url, "
                "https://www.ecfr.gov/current/title-<title>/section-<section>. "
                "fedregs_regulations_browse_cfr walks a title or part when the section is not known. "
                "fedregs_regulations_search_rules finds Federal Register proposed and final rules and "
                "fedregs_regulations_get_document reads one by its FR document number; register those at "
                "https://www.federalregister.gov/d/<FR number>. ecfr.gov and federalregister.gov pages "
                "answer HTTP 200 with a 10 KB «Request Access» stub to any non-browser client, so a "
                "WebFetch of them is never a source. When the server is down their open APIs are the "
                "fallback, and the plugin sends the compressed Accept-Encoding they need: "
                "federalregister.gov/api/v1/documents.json is only read, through mf sources fetch, to "
                "find the rule, and the text of a section from the eCFR API is saved with "
                "mf sources save --url."
            ),
        },
    },
    "case_law": {
        "EU": {
            "tools": [
                "legalviz_get_case_law",
                "legalviz_get_citing_provisions",
                "justicelibre_search_cjue",
                "justicelibre_get_decision_cjue",
                "ldh_resolve_reference",
                "ldh_search",
                "WebFetch",
            ],
            "ldh_sources": ["EU/CURIA"],
            "domains": ["publications.europa.eu", "eur-lex.europa.eu"],
            "note": (
                "legalviz_get_case_law and legalviz_get_citing_provisions find which CJEU judgments "
                "interpret the provision (case number, ECLI, date, name, articles) — they answer with "
                "that metadata, not with the judgment text; read the judgment itself through "
                "ldh_resolve_reference / ldh_search on EU/CURIA or a WebFetch of its CELEX text. "
                "justicelibre_search_cjue and justicelibre_get_decision_cjue are the alternative "
                "text source for a CJEU judgment when Cellar and LDH are both unavailable; the "
                "citation stays the CELEX address. A "
                "judgment carries the CELEX form 6<year>CJ<number> (C-252/21 is 62021CJ0252) on both "
                "hosts: https://publications.europa.eu/resource/celex/62021CJ0252 with "
                "Accept: application/xhtml+xml, and "
                "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62021CJ0252. Cellar serves "
                "the older judgments too and stays up while EUR-Lex is in a WAF window, so it comes "
                "first. curia.europa.eu is off the table altogether: liste.jsf, celex.jsf, "
                "document.jsf and showPdf.jsf all answer with the same 130 KB JavaScript shell for "
                "every case number, so it is neither a document nor a citation."
            ),
        },
        "UK": {
            "tools": [
                "uklegal_case_law_search",
                "uklegal_judgment_get_header",
                "uklegal_judgment_get_index",
                "uklegal_judgment_get_paragraph",
                "WebFetch",
            ],
            "ldh_sources": [],
            "domains": ["caselaw.nationalarchives.gov.uk"],
            "note": (
                "uklegal_case_law_search over Find Case Law, then judgment_get_header for the "
                "parties, neutral citation, court and dates, judgment_get_index for the structure "
                "and judgment_get_paragraph (or case_law_grep_judgment) for the pinpoint paragraph. "
                "uklegal_citations_resolve confirms the citation exists and "
                "uklegal_citations_format_oscola formats it. WebFetch "
                "caselaw.nationalarchives.gov.uk when the server is unavailable; BAILII is excluded "
                "by its own terms."
            ),
        },
        "US": {
            "tools": ["courtlistener_search", "courtlistener_analyze_citations", "WebFetch"],
            "ldh_sources": [],
            "domains": ["courtlistener.com", "supremecourt.gov"],
            "note": (
                "CourtListener MCP; extract_citations/analyze_citations verify existence. The MCP "
                "endpoint needs an OAuth token, and the courtlistener.com HTML pages sit behind an "
                "AWS WAF challenge (HTTP 202, empty body), so such a page is not a --url. With the "
                "server unavailable, the anonymous REST search "
                "courtlistener.com/api/rest/v4/search/ still answers; the document endpoints under "
                "/api/rest/v4/ require a token."
            ),
        },
    },
    "doctrine": {
        "EU": {
            "tools": ["WebSearch", "ldh_search", "WebFetch"],
            "ldh_sources": ["EU/EDPB", "EU/GDPRhub"],
            "domains": ["edpb.europa.eu", "europa.eu"],
            "note": "EDPB via LDH with a mandatory WebFetch fallback to edpb.europa.eu.",
        },
        "UK": {
            "tools": ["WebSearch", "ldh_search", "WebFetch"],
            "ldh_sources": ["UK/ICO"],
            "domains": ["ico.org.uk"],
            "note": "ICO guidance is the primary regulatory source for the UK.",
        },
        "US": {
            "tools": ["WebSearch", "WebFetch"],
            "ldh_sources": [],
            "domains": ["ftc.gov", "govinfo.gov"],
            "note": "Regulator guidance and peer-reviewed publications.",
        },
    },
}


# --- member states (§4.3; the national law behind the EU row) --------------

MEMBER_STATES: tuple[str, ...] = ("DE", "FR", "IE", "NL", "ES", "IT", "AT")
"""EU/EEA states whose own statute book and supervisory authority the table knows."""

_MEMBER_STATE_PORTALS: dict[str, tuple[str, ...]] = {
    "DE": ("gesetze-im-internet.de", "dejure.org", "buzer.de"),
    "FR": ("code.travail.gouv.fr", "legifrance.gouv.fr"),
    "IE": ("irishstatutebook.ie",),
    "NL": ("wetten.overheid.nl",),
    "ES": ("boe.es",),
    "IT": ("normattiva.it",),
    "AT": ("data.bka.gv.at", "ris.bka.gv.at"),
}
"""Official statute portals, first entry preferred; all of them are in `hooks/allowlist.txt`."""

_MEMBER_STATE_DPAS: dict[str, tuple[str, ...]] = {
    "DE": ("bfdi.bund.de", "datenschutzkonferenz-online.de"),
    "FR": ("cnil.fr",),
    "IE": ("dpc.ie",),
    "NL": ("autoriteitpersoonsgegevens.nl",),
    "ES": ("aepd.es",),
    "IT": ("garanteprivacy.it",),
    "AT": ("dsb.gv.at",),
}
"""National supervisory authorities — the doctrine source for a member state (Article 35(4) lists)."""

_MEMBER_STATE_STATUTE_NOTE = (
    "LegalViz reads Union law only, so a member state starts at its own official statute portal "
    "and uses ldh_search for what the portal will not serve. The provision is saved from its "
    "portal page with mf sources save --url (a portal off the allowlist is the host_not_allowed "
    "case); what ldh_search answers is registered as it is, --raw-kind excerpt."
)

_MEMBER_STATE_STATUTE_BASE: dict[str, str] = {
    "FR": (
        "LegalViz reads Union law only, and France is the one member state whose statute book is "
        "not fetched at all: the bundled justicelibre server serves it."
    ),
}
"""States whose first sentence is not the generic «start at the portal» rule (D-148)."""

_MEMBER_STATE_STATUTE_TOOLS: dict[str, list[str]] = {
    "FR": [
        "justicelibre_get_law_article",
        "justicelibre_resolve_law_number",
        "ldh_resolve_reference",
        "WebFetch",
    ],
}
"""Tool order of a state whose row is not the default `WebFetch` → `ldh_search` (D-148)."""

_MEMBER_STATE_STATUTE_EXTRA: dict[str, str] = {
    "DE": (
        " gesetze-im-internet.de carries the official English translations under "
        "/englisch_<act>/ (BDSG is /englisch_bdsg), but that translation is one 194 KB page with no "
        "per-section anchors, so a pinpoint citation takes the German original "
        "/bdsg_2018/__<N>.html. ldh_search does not index the BDSG at all — dejure.org and buzer.de "
        "are the mirrors for a section the portal refuses. The bulk channel is "
        "gesetze-im-internet.de/gii-toc.xml, the index of all 6 130 consolidated acts, each with an "
        "<act>/xml.zip whose <norm> elements are one section apiece (<enbez>§ N). NeuRIS "
        "(rechtsinformationen.bund.de) is a declared trial with an incomplete dataset and holds "
        "texts as promulgated in the BGBl, not consolidated law, so it does not replace the portal."
    ),
    "FR": (
        " justicelibre_get_law_article is the route, and its contract is exact: the parameters are "
        "code=<short abbreviation> and num=<article>, not a title and not `article` — "
        "get_law_article(code=\"CT\", num=\"L1121-1\") answers with the text of Article L1121-1 of "
        "the Code du travail plus legiarti, legitext, etat: VIGUEUR, date_debut and a source_url on "
        "Légifrance. That source_url is the registered address (--tool "
        "justicelibre_get_law_article), never the MCP endpoint. A wrong code is not a dead end: the "
        "server answers with the full list of the 79 abbreviations it supports (CC, CP, CPC, CPP, "
        "CT, CSP, CJA, CGI, CSS, CESEDA, CONST …), and justicelibre_resolve_law_number finds the "
        "LEGITEXT/JORFTEXT of a law or decree outside the codes. The reserve is "
        "ldh_resolve_reference on FR/LegifranceCodes — 229 364 articles of every consolidated "
        "French code, not the 882-decision FR/legifrance case-law base — called with the exact "
        "citation; ldh_search is not a search engine for it and returns noise. "
        "legifrance.gouv.fr itself is closed by a Cloudflare managed challenge: 403 on every path, "
        "/robots.txt included, for any client without JavaScript and cookies, so it is the "
        "registered URL and never a WebFetch target. code.travail.gouv.fr is the keyless fallback "
        "that does serve text — code.travail.gouv.fr/code-du-travail/<article> answers 200 with the "
        "article and its LEGIARTI — but it carries the Code du travail alone."
    ),
    "IT": (
        " normattiva.it serves article text only inside a session (a cookie plus the landing page "
        "as Referer); a bare GET of atto/caricaArticolo answers 500. The stateless pinpoint is the "
        "official open-data API, https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1 "
        "— OpenAPI 3.0.1 with no authorisation: POST /atto/dettaglio-atto-urn with an URN of the "
        "form urn:nir:stato:decreto.legislativo:2003-06-30;196~artN!vig=YYYY-MM-DD returns that one "
        "article as it stood on that date, under CC BY 4.0. The call needs a request body and a "
        "Content-Type, so the article is saved by mf sources save, not WebFetch — exactly this "
        "command (D-151, D-205): `mf sources save --workdir <task> --layer statutes "
        "--title \"D.Lgs. 196/2003, art. 7\" --citation \"D.Lgs. 30 giugno 2003, n. 196, art. 7\" "
        "--tier critical --url "
        "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/atto/dettaglio-atto-urn "
        "--method POST --json "
        "'{\"urn\": \"urn:nir:stato:decreto.legislativo:2003-06-30;196~art7!vig=2026-01-01\"}' "
        "--public-url "
        "'https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2003-06-30;196~art7"
        "!vig=2026-01-01'`, where the date after !vig= is the version date asked for. The API "
        "address answers every article, so it names none and a client cannot open it: --public-url "
        "is the article's own page, https://www.normattiva.it/uri-res/N2Ls? followed by the same URN "
        "as the body, and save stores it as the record's url (a POST save without it is refused)."
    ),
    "ES": (
        " the consolidated text comes from the BOE open-data API, "
        "boe.es/datosabiertos/api/legislacion-consolidada/id/{id}/texto/bloque/{aN}, one block per "
        "article. It refuses a request without an Accept header (400 «No soportado ningún mime "
        "type») and that endpoint answers only to Accept: application/xml, so the block is saved "
        "by mf sources save with --accept application/xml, not by WebFetch."
    ),
    "NL": (
        " wetten.overheid.nl/xml.php no longer exists (404). The BWB text is reached through "
        "repository.officiele-overheidspublicaties.nl/bwb/{BWBID}/_manifest.xml, whose _latestItem "
        "names the current toestand XML with one <artikel> per article; the SRU endpoint at "
        "zoekservice.overheid.nl is the search front for it. All of them need Accept: "
        "application/xml, which WebFetch cannot send: the manifest and the SRU search are only read, "
        "through mf sources fetch (D-149), and the toestand XML the manifest names is the text, "
        "saved by mf sources save --url with --accept application/xml."
    ),
    "IE": (
        " irishstatutebook.ie serves a section as HTML (/eli/<year>/act/<n>/section/<s>/enacted/"
        "en/html answers 200) but not as XML — the per-section XML path is 404 and only the whole "
        "act is available at /enacted/en/xml. The data is CC BY 4.0, the cleanest licence of the "
        "member-state portals."
    ),
    "AT": (
        " www.ris.bka.gv.at answers 503 to a bot check on every path, so the route is the open-data "
        "API in two steps: data.bka.gv.at/ris/api/v2.6/Bundesrecht"
        "?Applikation=BrKons&Gesetzesnummer=<N>&DokumenteProSeite=Ten returns JSON whose "
        "Dokumentliste…ContentUrl carries the Html entry, and that entry is "
        "ogd.ris.bka.gv.at/Dokumente/Bundesnormen/<NOR>/<NOR>.html. On the ogd host only the "
        "/Dokumente/… paths work. The OGD usage conditions bind: at most 0.5 requests per second, "
        "no parallel connections, bulk reading only between 20:00 and 05:00 or at weekends and on "
        "public holidays, and a notice to ris.it@bka.gv.at before any mass use — breaching them "
        "gets the IP blocked."
    ),
}

_MEMBER_STATE_DOCTRINE_NOTE = (
    "The national supervisory authority is the doctrine source for this state: its own guidance "
    "and its published Article 35(4) list of processing that always needs a DPIA. WebSearch "
    "locates the page, the authority's own site is the citation."
)

_MEMBER_STATE_DOCTRINE_EXTRA: dict[str, str] = {
    "FR": (
        " justicelibre_search_cnil reads the CNIL's own deliberations and sanctions, and "
        "justicelibre_search_doctrine the wider French commentary; both come before WebSearch."
    ),
}

MEMBER_STATE_ROWS: dict[str, dict[str, dict]] = {
    "statutes": {
        code: {
            "tools": list(_MEMBER_STATE_STATUTE_TOOLS.get(code, ["WebFetch", "ldh_search"])),
            "ldh_sources": [],
            "domains": list(domains),
            "note": _MEMBER_STATE_STATUTE_BASE.get(code, _MEMBER_STATE_STATUTE_NOTE)
            + _MEMBER_STATE_STATUTE_EXTRA.get(code, ""),
        }
        for code, domains in _MEMBER_STATE_PORTALS.items()
    },
    "case_law": {
        "FR": {
            "tools": [
                "justicelibre_search_judiciaire",
                "justicelibre_get_decision_judiciaire",
                "justicelibre_search_conseil_etat",
                "justicelibre_get_ce_decision",
                "justicelibre_search_cc",
            ],
            "ldh_sources": ["FR/Judilibre"],
            "domains": ["courdecassation.fr"],
            "note": (
                "justicelibre covers the three French orders: search_judiciaire and "
                "get_decision_judiciaire for the Cour de cassation and the courts below it, "
                "search_conseil_etat and get_ce_decision for the administrative order, search_cc "
                "for the Conseil constitutionnel. The decision text the tool returns is the source; "
                "courdecassation.fr/decision/<id> is not a --url, because it answers HTTP 200 with "
                "a 255-byte JavaScript redirect shell and no decision in it. Register the decision "
                "under the tool that returned it, with the ECLI in --citation."
            ),
        },
    },
    "doctrine": {
        code: {
            "tools": (
                ["justicelibre_search_cnil", "justicelibre_search_doctrine", "WebSearch", "WebFetch"]
                if code == "FR"
                else ["WebSearch", "ldh_search", "WebFetch"]
            ),
            "ldh_sources": [],
            "domains": list(domains),
            "note": _MEMBER_STATE_DOCTRINE_NOTE + _MEMBER_STATE_DOCTRINE_EXTRA.get(code, ""),
        }
        for code, domains in _MEMBER_STATE_DPAS.items()
    },
}
"""Rows `route()` finds after `ROUTING`, kept apart from it because `ROUTING` also drives the six
lines of `routing_digest` (D-110): the intake analyst is told about EU/UK/US, not about every state.
`case_law` holds France alone (D-148): the other states' own courts stay off-table, and
`known: False` says so."""

_UA_TOOL_NAMES_NOTE = (
    "The tool names in this row are the vendor's documented ones; the exact names are the tools "
    "the host exposes under that server's namespace — an opaque connector namespace in Cowork — so "
    "match by tool suffix and call what the host offers when the two differ."
)
"""The researcher's fallback for a tool name that moved — the host's own tool list."""

_UA_STATUTE_SAVE = (
    "mf sources save --workdir <work_dir> --layer statutes --title \"ЦК України, ст. 257\" "
    "--citation \"Цивільний кодекс України від 16.01.2003 № 435-IV, ст. 257\" --tier critical "
    "--url https://zakon.rada.gov.ua/laws/show/435-15 --expect-article 257 "
    "--meta '{\"edition\": \"<the «Редакція від …» line of the page>\", \"short_name\": \"ЦК України\"}'"
)
_UA_COURT_SAVE = (
    "mf sources save --workdir <work_dir> --layer case_law "
    "--title \"ВС (КАС), ухвала у справі № 640/9591/20 від 05.01.2026\" "
    "--citation \"Ухвала Верховного Суду у складі колегії суддів Касаційного адміністративного суду "
    "від 05.01.2026 у справі № 640/9591/20\" --tier critical "
    "--url https://reyestr.court.gov.ua/Review/133126382 --expect-number 640/9591/20 --expect-date 2026-01-05"
)
_UA_LDH_EXCERPT = (
    "mf sources register --workdir <work_dir> --layer statutes --title \"ЦК України, ст. 257\" "
    "--citation \"Цивільний кодекс України від 16.01.2003 № 435-IV, ст. 257\" "
    "--tier critical --tool ldh_search --raw-kind excerpt "
    "--raw-file \"<a file holding the answer as LDH returned it>\""
)
"""The commands the UA notes print, each one a line `mf` accepts (`test_routing` splits them as a
shell would and hands them to the real parser, so a misspelt flag fails there).

The court act is a real one found through LDH (UA/SupremeCourt, source_id UA-SC-133126382): a ruling
of a panel of the Cassation Administrative Court of the Supreme Court of 05.01.2026 in case
640/9591/20, whose public page is the Unified State Register of Court Decisions. The statute line
saves one article of the Civil Code from the Verkhovna Rada portal; the last line is the fallback
that registers LDH's own article answer as an excerpt when the portal page cannot be fetched.
"""

EXTRA_JURISDICTION_ROWS: dict[str, dict[str, dict]] = {
    "statutes": {
        "UA": {
            "tools": ["ldh_search", "ldh_get_document", "WebFetch"],
            "ldh_sources": ["UA/RadaLegislation", "UA/NBU-Regulations"],
            "domains": ["zakon.rada.gov.ua"],
            "note": (
                "LDH's UA/RadaLegislation carries the acts of the Verkhovna Rada portal "
                "(zakon.rada.gov.ua) and indexes the codes article by article: a hit is a unit with "
                "source_id `<act id>#art=<n>` (the Civil Code is `435-15#art=257`), a canonical_path "
                "through the section and chapter, the act's date and the portal address of the whole "
                "act. Search in Ukrainian with the act name and the article number; the answer for "
                "an article is the text in force as LDH last indexed it, so the edition date is not "
                "known from it. The index holds only part of the portal (a few thousand of its "
                "acts): an act that does not come back is not thereby absent from the portal — search "
                "again by the act's number (`435-15`) and by its full Ukrainian title before saying "
                "that the text was not retrieved; ldh_resolve_reference does not resolve Ukrainian "
                "references. ldh_get_document takes the source and the unit's source_id "
                "(UA/RadaLegislation, `435-15#art=257`) and returns the article as indexed. "
                "UA/NBU-Regulations holds the acts of the National Bank of Ukraine. The source is one "
                "article, saved by code from the page of the act on zakon.rada.gov.ua (the current "
                "wording; each earlier wording has its own address with the edition date) with the "
                "edition line the page prints in --meta: `" + _UA_STATUTE_SAVE + "`. zakon.rada.gov.ua "
                "refuses robots, so WebFetch and the shell may be turned away from it; when the save "
                "is refused, register LDH's own article answer as it is (--raw-kind excerpt), `"
                + _UA_LDH_EXCERPT + "`, and cite it as an excerpt with the edition left unconfirmed. "
                + _UA_TOOL_NAMES_NOTE + " Write the pinpoint exactly as the source numbers it — ст. 257, "
                "ч. 1 ст. 257, п. 2 ч. 1 ст. 257, абз. 2 ч. 1 ст. 257 (Cyrillic labels ст, ч, п, пп, "
                "абз, each with its number) — never art 257(1); the statute's registered citation form "
                "is the Ukrainian one (Цивільний кодекс України від 16.01.2003 № 435-IV, ст. 257): the "
                "act's title, its date and its number as the portal prints them. A contract or an "
                "offer the client supplied is pinpointed the same way, by its own clause numbers and "
                "section headings (розд, розділ, гл, дод) with the heading left as the document wrote "
                "it — п. 3 розд. «Відшкодування», п. 5.1 розд. «Відповідальність»."
            ),
        },
        "CH": {
            "tools": [
                "opencaselaw_get_law",
                "opencaselaw_search_laws",
                "opencaselaw_get_article_history",
                "WebFetch",
            ],
            "ldh_sources": [],
            "domains": ["fedlex.admin.ch"],
            "note": (
                "Switzerland is not an EU member state and LegalViz does not read it; the bundled "
                "opencaselaw server does. opencaselaw_get_law takes sr_number and article — "
                "get_law(sr_number=\"220\", article=\"328b\") returns Art. 328b OR with the "
                "consolidation date and a Fedlex source_url "
                "(fedlex.admin.ch/eli/cc/…/de#art_328b), which is the address to register. The "
                "answer also names the consolidations already scheduled («a consolidation of this "
                "act enters into force on <date>»), so it is the currency check for Swiss law as "
                "well. opencaselaw_search_laws finds the SR number, opencaselaw_get_article_history "
                "the earlier wordings. An unrecognised parameter is reported, not swallowed."
            ),
        },
    },
    "case_law": {
        "UA": {
            "tools": ["ldh_search", "ldh_get_document", "WebSearch", "WebFetch"],
            "ldh_sources": ["UA/SupremeCourt", "UA/ConstitutionalCourt", "UA/HACC"],
            "domains": ["reyestr.court.gov.ua", "supreme.court.gov.ua"],
            "note": (
                "LDH's UA/SupremeCourt holds the acts of the Supreme Court — the Grand Chamber and "
                "the cassation courts — for 2023–2026, with the public page of the Unified State "
                "Register of Court Decisions (reyestr.court.gov.ua/Review/<id>) as the url of each "
                "hit; search in Ukrainian and filter by date. UA/ConstitutionalCourt holds the "
                "decisions and opinions of the Constitutional Court from 1997. UA/HACC holds a "
                "handful of acts of the High Anti-Corruption Court. Acts of the Supreme Court before "
                "2023 and of the courts of first and appellate instance are not in LDH: "
                "UA/EDRSR covers 2005–2006 only and UA/REYESTR-CourtDecisions a dozen documents, so "
                "neither is a source for current practice. For an older act or a lower court, take "
                "the case number from a web search or from the client's papers and save the "
                "register page; never rely on a search snippet as the act's text. The act is saved "
                "by code from its register page: `" + _UA_COURT_SAVE + "`. The number goes in "
                "whole, as the heading of the act prints it (справа № 640/9591/20), and the date is "
                "the date of the act itself, not of its publication in the register. The texts in "
                "the register are anonymised (ОСОБА_1, ОСОБА_2): cite a decision by the court, the "
                "date and the case number, never by the parties. " + _UA_TOOL_NAMES_NOTE + " Pass the "
                "decision's citation form in Ukrainian as --citation (Постанова Великої Палати "
                "Верховного Суду від … у справі № …; Постанова Касаційного цивільного суду у складі "
                "Верховного Суду від … у справі № …; Ухвала …; Рішення Конституційного Суду України "
                "від … № …-р/…) and pinpoint by п. N (пункт мотивувальної частини) where the text is "
                "numbered, else no pinpoint. When the register page cannot be fetched, register LDH's "
                "own answer as it is (--raw-kind excerpt) and cite it as an excerpt."
            ),
        },
        "CH": {
            "tools": [
                "opencaselaw_search_decisions",
                "opencaselaw_get_decision",
                "opencaselaw_get_regeste",
                "opencaselaw_find_leading_cases",
                "WebFetch",
            ],
            "ldh_sources": [],
            "domains": ["bger.ch"],
            "note": (
                "opencaselaw_search_decisions over the federal and cantonal corpus, "
                "opencaselaw_get_decision for the text, opencaselaw_get_regeste for the official "
                "headnote and opencaselaw_find_leading_cases for the BGE line on a question. The "
                "data is CC0, the citation is the BGE/BGer reference and the registered URL is the "
                "decision on bger.ch. entscheidsuche.ch has its own MCP server, but it is not "
                "bundled — do not route to it."
            ),
        },
    },
    "doctrine": {
        "UA": {
            "tools": ["ldh_search", "WebSearch", "WebFetch"],
            "ldh_sources": ["UA/NAZK"],
            "domains": ["nazk.gov.ua", "nbuv.gov.ua"],
            "note": (
                "UA/NAZK carries the explanations, methodological recommendations and legal "
                "positions of the National Agency on Corruption Prevention (2011–2024) — the "
                "regulatory source on conflicts of interest, declarations and anti-corruption "
                "programmes. Commentaries and articles come from a web search; nbuv.gov.ua (the "
                "Vernadsky National Library) indexes the Ukrainian scholarly journals. Cite the "
                "author, the title and the outlet, and the NAZK document by its own title and date. "
                + _UA_TOOL_NAMES_NOTE
            ),
        },
        "CH": {
            "tools": [
                "opencaselaw_get_doctrine",
                "opencaselaw_search_commentaries",
                "WebSearch",
                "WebFetch",
            ],
            "ldh_sources": [],
            "domains": ["edoeb.admin.ch"],
            "note": (
                "opencaselaw_get_doctrine and opencaselaw_search_commentaries read the Swiss "
                "commentary literature; the federal supervisory authority (edoeb.admin.ch) is the "
                "regulatory source and the citation for its own guidance."
            ),
        },
    },
}
"""Jurisdictions outside `MEMBER_STATES` that a bundled server covers end to end (D-148).

`MEMBER_STATES` stays an EU/EEA list — it drives the member-state sweep of `preflight` and the
«EEA member states» expansion — so Switzerland lives here and is merged in by `route()` alone.
"""


def route(layer: str, jurisdiction: object) -> dict:
    """Tool order and preferred domains for one `layer x jurisdiction` pair (§4.3)."""
    if layer not in ROUTING:
        raise ValueError(f"unknown_layer: {layer!r}")
    code = normalize_jurisdiction(jurisdiction)
    row = (
        ROUTING[layer].get(code)
        or MEMBER_STATE_ROWS.get(layer, {}).get(code)
        or EXTRA_JURISDICTION_ROWS.get(layer, {}).get(code)
    )
    known = row is not None
    if row is None:
        row = _DEFAULT_ROWS[layer]
    result = {
        "layer": layer,
        "jurisdiction": code,
        "tools": list(row.get("tools", [])),
        "ldh_sources": list(row.get("ldh_sources", [])),
        "domains": list(row.get("domains", [])),
        "note": row.get("note", ""),
        "known": known,
        "member_state_generic": _upper(jurisdiction) in MEMBER_STATE_GENERIC,
    }
    return result


def routing_for(layers: list[str] | tuple[str, ...], jurisdictions: list[str] | tuple[str, ...]) -> list[dict]:
    """The ready-made `routing[]` parameter of `legal-researcher` (§4.3)."""
    rows: list[dict] = []
    for layer in layers:
        for jurisdiction in jurisdictions or [""]:
            rows.append(route(layer, jurisdiction))
    return rows


# --- MCP budget estimate (§4.3) -------------------------------------------


def estimate_calls(layers: list[str] | tuple[str, ...], issues: int) -> dict:
    """`layers x issues x 2` plus the intake/currency share, compared against the daily caps (§4.3)."""
    layer_count = len(list(layers))
    issue_count = max(int(issues), 0)
    research = layer_count * issue_count * 2
    currency = layer_count * limits.MCP_CURRENCY_CALLS_PER_LAYER
    intake = limits.MCP_INTAKE_CALLS
    total = research + currency + intake
    return {
        "layers": layer_count,
        "issues": issue_count,
        "research": research,
        "currency": currency,
        "intake": intake,
        "total": total,
        "provider_daily_limits": dict(limits.MCP_PROVIDER_DAILY_LIMITS),
    }


def budget_verdict(layers: list[str] | tuple[str, ...], issues: int, mcp_budget: dict | None) -> dict:
    """True `exceeds` when the estimate is above the daily quota of the quota servers (D-166)."""
    estimate = estimate_calls(layers, issues)
    budget = dict(mcp_budget or {})
    daily = sum(limits.MCP_PROVIDER_DAILY_LIMITS[s] for s in limits.MCP_QUOTA_SERVERS if s in budget)
    estimate["daily_upper_bound"] = daily
    estimate["exceeds_daily_upper_bound"] = bool(daily) and estimate["total"] > daily
    estimate["exceeds"] = estimate["exceeds_daily_upper_bound"]
    return estimate


# --- discover cache -------------------------------------------------------


def discover_cache_path() -> Path:
    """Absolute path of `lib/routing/discover-cache.json` inside the plugin."""
    return pylauncher.plugin_root() / "lib" / "routing" / "discover-cache.json"


def discover_cache() -> dict:
    """Read the cached LDH source names; an unreadable cache is not fatal (§4.3)."""
    from . import state_io

    try:
        data = state_io.read_json(discover_cache_path())
    except (OSError, ValueError):
        return {"schema_version": 1, "kind": "routing", "entries": {}}
    return data if isinstance(data, dict) else {"schema_version": 1, "kind": "routing", "entries": {}}


def ldh_sources(country: object) -> list[str]:
    """Cached LDH source names for one country code (normalised: `GB` -> `UK`)."""
    entries = discover_cache().get("entries") or {}
    row = entries.get(normalize_jurisdiction(country)) or {}
    return [str(name) for name in (row.get("sources") or [])]
