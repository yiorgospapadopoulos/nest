"""Codex's own questions to the user (`request_user_input`, B112) as Nest's questions, the
same card Claude's AskUserQuestion gets.

Codex asks with the experimental `item/tool/requestUserInput` request: one to three
questions, each with an id, a header, its text and options (label and description), and
`isOther` when a free answer is welcome. It is answered with the answers by question id,
each a list of strings: the chosen option's label, or a free answer as `user_note: <text>`
beside options, as Codex's own clients answer. A dismissed card answers nothing, which
Codex reads as "go on with your best judgment".
"""

from pydantic import JsonValue

from nestd.providers.base import Question, QuestionAnswer, QuestionOption, QuestionRequest
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_rpc import JsonObject

USER_INPUT = "item/tool/requestUserInput"
NOTE = "user_note: "


def question_request(params: JsonObject) -> QuestionRequest:
    return QuestionRequest(
        questions=tuple(_question(obj(raw)) for raw in items(params.get("questions"))),
        tool_use_id=text(params.get("itemId")) or None,
    )


def user_input_answer(params: JsonObject, answer: QuestionAnswer) -> JsonValue:
    """Nest's answers (by question text) as Codex's (by question id)."""
    answers: dict[str, JsonValue] = {}
    given = answer.answers or {}
    for raw in items(params.get("questions")):
        question = obj(raw)
        reply = given.get(text(question.get("question")))
        if reply is None:
            continue
        labels = {text(obj(option).get("label")) for option in items(question.get("options"))}
        labels.discard("")
        value = reply if reply in labels or not labels else NOTE + reply
        answers[text(question.get("id"))] = {"answers": [value]}
    return {"answers": answers}


def _question(raw: JsonObject) -> Question:
    header = text(raw.get("header"))
    return Question(
        question=text(raw.get("question")),
        header=header or None,
        options=tuple(
            QuestionOption(
                label=text(option.get("label")),
                description=text(option.get("description")) or None,
            )
            for option in (obj(entry) for entry in items(raw.get("options")))
            if text(option.get("label"))
        ),
        multi_select=False,
    )
