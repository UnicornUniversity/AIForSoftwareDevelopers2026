import json

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from uda.fixtures import load_demo_schema
from uda.workflow import run_workflow


def _model(payload: str) -> FakeListChatModel:
    return FakeListChatModel(responses=[payload])


def _valid_payload() -> str:
    return json.dumps(
        {
            "concept_name": "Customer",
            "description": "A person who buys from the store.",
            "attributes": [
                {
                    "attribute": "identifier",
                    "description": "The customer's unique identifier.",
                    "column": "customer_id",
                },
                {
                    "attribute": "name",
                    "description": "The customer's full name.",
                    "column": "full_name",
                },
            ],
        }
    )


def test_valid_response_builds_pending_candidate() -> None:
    result = run_workflow(load_demo_schema(), _model(_valid_payload()))

    assert result.ok
    assert result.error is None
    assert result.issues == ()
    assert result.candidate is not None
    assert result.candidate.status == "pending_review"
    assert result.candidate.physical_table == "dbo.Customer"
    assert result.candidate.concept.concept_name == "Customer"


def test_fenced_json_is_accepted() -> None:
    payload = "```json\n" + _valid_payload() + "\n```"

    result = run_workflow(load_demo_schema(), _model(payload))

    assert result.ok


def test_malformed_response_becomes_error_without_candidate() -> None:
    result = run_workflow(load_demo_schema(), _model("I cannot help with that."))

    assert not result.ok
    assert result.candidate is None
    assert result.proposal is None
    assert result.error is not None
    assert result.error.startswith("LLM response is not a valid proposal")


def test_wrong_shape_becomes_error_without_candidate() -> None:
    result = run_workflow(load_demo_schema(), _model('{"concept_name": "Only"}'))

    assert result.error is not None
    assert result.candidate is None


def test_unknown_column_is_reported_and_not_built() -> None:
    payload = json.dumps(
        {
            "concept_name": "Customer",
            "description": "A person.",
            "attributes": [
                {
                    "attribute": "identifier",
                    "description": "The customer's unique identifier.",
                    "column": "customer_key",
                }
            ],
        }
    )

    result = run_workflow(load_demo_schema(), _model(payload))

    assert result.error is None
    assert result.proposal is not None
    assert result.candidate is None
    assert [issue.code for issue in result.issues] == ["unknown_column"]


def test_multi_column_mapping_builds_candidate() -> None:
    payload = json.dumps(
        {
            "concept_name": "Customer",
            "description": "A person.",
            "attributes": [
                {
                    "attribute": "contact",
                    "description": "How to reach the customer.",
                    "column_names": ["full_name", "email"],
                }
            ],
        }
    )

    result = run_workflow(load_demo_schema(), _model(payload))

    assert result.ok
    assert result.candidate is not None
    assert result.candidate.concept.attributes[0].column_names == (
        "full_name",
        "email",
    )


def test_duplicate_mapping_is_reported_and_not_built() -> None:
    payload = json.dumps(
        {
            "concept_name": "Customer",
            "description": "A person.",
            "attributes": [
                {
                    "attribute": "identifier",
                    "description": "The customer's unique identifier.",
                    "column": "customer_id",
                },
                {
                    "attribute": "key",
                    "description": "A second reference to the identifier.",
                    "column": "Customer_ID",
                },
            ],
        }
    )

    result = run_workflow(load_demo_schema(), _model(payload))

    assert result.error is None
    assert result.candidate is None
    assert [issue.code for issue in result.issues] == ["duplicate_column_mapping"]
