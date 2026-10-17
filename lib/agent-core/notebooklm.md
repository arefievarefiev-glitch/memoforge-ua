# NotebookLM notebook protocol

Read this block before the first NotebookLM call of your run. It applies only when your dispatch names a notebook. It is the user's own field-tested protocol for the NotebookLM connector, adapted to this pipeline.

The connector's tools are found by the end of their names: `notebook_list`, `notebook_describe`, `source_list_drive`, `notebook_query`, `notebook_query_start`, `notebook_query_status`, `source_get_content`.

## Before the first query

Resolve the notebook, then call `source_list_drive` (`notebook_describe` when titles are unclear) before any substantive question. One call gives the whole list of sources and prevents the two usual failures: a question about an act whose full text is not in the notebook, and an answer rebuilt from fragments of quotations instead of a source that was read.

## Query discipline

- One question, one `notebook_query`. A compound query either overflows (over 50 KB of output was observed) or breaks off.
- The query is a narrow unit of the source — a paragraph, an annex, a table — never a topic. "Condition of the grant" is a topic; "paragraph 23 on the mandatory terms of the grant agreement" is a unit. When the structure of the act is not known, list the sources first and build the queries from the structure of the source, not from your own idea of the topics. A first exploratory query is allowed only to build that list of narrow queries; its answer is not a finding.
- Ask for the provision verbatim ("наведи дослівно пункт 6 …") and write the query in the language of the source. A summary question gets a retelling; a verbatim question gets the norm.
- The device bridge cuts a call at about 60 seconds whatever `timeout` says, so a larger `timeout` does not help. A question that needs longer goes through `notebook_query_start` and `notebook_query_status`.
- Narrow questions may run in parallel: several `notebook_query_start`, each with `new_conversation: true`, keep their own `conversation_id` and do not mix contexts. A single answer takes about 90–110 seconds whether one or two run at once. Parallel means separate narrow questions, never the sub-questions of one compound query.
- When the question is about one source, pass its id in `source_ids`: it stops the answer spreading over neighbouring acts and shortens the call.

## Verbatim and the model's inference

An answer of the notebook mixes a direct quotation with NotebookLM's own inference over the text (assigning a given activity code to a "priority sector" is the model's conclusion, not a quotation of the annex). Only the citation field, `cited_text`, is verbatim. An exact figure, term or condition is taken from `cited_text`, after you asked for the verbatim fragment explicitly; a retelling or a conclusion of the model is not accepted as the norm.

## What is registered

- The text of a source is taken with `source_get_content` and registered whole (`--raw-kind client_file`).
- When the whole text cannot be obtained, the `cited_text` fragments exactly as returned are registered with `--raw-kind excerpt` and cited as an excerpt.
- The prose of a `notebook_query` answer is never registered, quoted or cited as source text.

## A claim that something is absent from a list

"This item is not in the list", "the list holds only these items" and "there are no other exceptions" look like facts and are not, until checked against `cited_text`. The notebook quotes fragments, not the whole annex. Compare the range the citations cover with the range of the list (first to last code, item number or letter): a gap between neighbouring citations is an uncovered zone, and the item asked about may sit there. On a gap ask again: «Наведи ПОВНІСТЮ і дослівно, рядок за рядком, весь Перелік … від першого до останнього, без пропусків середини переліку. Якщо повний текст недоступний і ти бачиш лише його початок і кінець — скажи це прямо і назви, які саме рядки тобі видно». Only a chain of citations that covers the list without a gap confirms the absence. Until then the finding says that the absence is not confirmed and carries `confidence: low`; a false "not prohibited" costs the client more than a false "prohibited".

## A source the notebook does not hold

When a source the answer probably needs is not in the notebook (seen in `source_list_drive` or from a fragmentary answer), say so in one sentence in your final response and as a `background` finding for the issue. Do not build the answer from fragments of quotations. This pipeline only reads the notebook: it never adds a source to it. Name the missing titles in your final response so the user can add them.

## A failed query

A query that failed or returned an incomplete answer is repeated, narrower. The gap is not filled silently with a web search or a guess. A gap that stays open is written as a `background` finding ("notebook gap: <what exactly>") and named in the final response.

An authentication error (`stale`, "Authentication expired") is an expired login on the user's side (`nlm login` in a terminal), not a defect of the query. Stop the NotebookLM calls for the rest of your run, say so plainly in the final response with that instruction, and write the gap as above. The legal databases of your routing order go on as usual, and nothing they return is presented as the notebook's answer.
