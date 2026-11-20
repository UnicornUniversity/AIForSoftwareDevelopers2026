from uda.fixtures import load_demo_schema


def test_demo_schema_loads() -> None:
    schema = load_demo_schema()

    assert schema.qualified_name == "dbo.Customer"


def test_demo_schema_has_the_documented_columns() -> None:
    schema = load_demo_schema()

    assert [column.name for column in schema.columns] == [
        "customer_id",
        "full_name",
        "email",
        "loyalty_tier",
        "signup_date",
        "is_active",
    ]


def test_demo_schema_identifier_is_not_nullable() -> None:
    schema = load_demo_schema()

    identifier = next(
        column for column in schema.columns if column.name == "customer_id"
    )

    assert identifier.nullable is False


def test_demo_schema_identifier_is_primary_key() -> None:
    schema = load_demo_schema()

    identifier = next(
        column for column in schema.columns if column.name == "customer_id"
    )

    assert identifier.is_primary_key is True
