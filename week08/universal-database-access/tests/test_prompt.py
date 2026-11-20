from uda.fixtures import load_demo_schema
from uda.prompt import SYSTEM_PROMPT, build_messages, render_table


def test_prompt_renders_every_column() -> None:
    schema = load_demo_schema()

    text = render_table(schema)

    assert "Table: dbo.Customer" in text
    for column in schema.columns:
        assert f"- {column.name} ({column.data_type}" in text
    assert "PK" in text


def test_messages_are_system_then_table() -> None:
    schema = load_demo_schema()

    messages = build_messages(schema)

    assert [type(message).__name__ for message in messages] == [
        "SystemMessage",
        "HumanMessage",
    ]
    assert "JSON only" in SYSTEM_PROMPT
    assert "pending review" in SYSTEM_PROMPT
    assert '"column_names"' in SYSTEM_PROMPT
    assert "customer_id" in messages[1].content


def test_prompt_is_deterministic_and_has_no_secret_material() -> None:
    schema = load_demo_schema()

    assert build_messages(schema) == build_messages(schema)
    combined = SYSTEM_PROMPT + render_table(schema)
    assert "api_key" not in combined.casefold()
    assert "password" not in combined.casefold()
