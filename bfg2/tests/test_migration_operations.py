from copy import deepcopy

import pytest
from django.db import connection, migrations, models
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ModelState, ProjectState

from bfg.core.migration_operations import (
    AddConstraintIfCompatible,
    AddFieldIfCompatible,
    AddIndexIfCompatible,
    CreateModelIfCompatible,
    SchemaRetryError,
    _normalise_expression,
)


APP_LABEL = "schema_retry_tests"
PARENT_TABLE = "schema_retry_parent"
RECORD_TABLE = "schema_retry_record"


def parent_state():
    state = ProjectState()
    state.add_model(
        ModelState(
            APP_LABEL,
            "Parent",
            [("id", models.BigAutoField(primary_key=True))],
            {"db_table": PARENT_TABLE},
        )
    )
    return state


def record_operation(
    *,
    code_length=32,
    include_index=True,
    index_fields=("parent", "-amount"),
    check="gte",
    amount_null=True,
    amount_digits=None,
    unique_fields=("parent", "status"),
):
    indexes = (
        [models.Index(fields=index_fields, name="retry_parent_amount_idx")]
        if include_index
        else []
    )
    condition = models.Q(amount__gte=0) if check == "gte" else models.Q(amount__lte=0)
    return CreateModelIfCompatible(
        name="Record",
        fields=[
            ("id", models.BigAutoField(primary_key=True)),
            (
                "parent",
                models.ForeignKey(
                    on_delete=models.PROTECT,
                    related_name="retry_records",
                    to=f"{APP_LABEL}.parent",
                ),
            ),
            ("code", models.CharField(max_length=code_length, unique=True)),
            ("label", models.CharField(db_index=True, max_length=40)),
            ("amount", (
                models.DecimalField(decimal_places=2, max_digits=amount_digits, null=amount_null)
                if amount_digits is not None
                else models.IntegerField(null=amount_null)
            )),
            ("status", models.CharField(max_length=16)),
        ],
        options={
            "db_table": RECORD_TABLE,
            "indexes": indexes,
            "constraints": [
                models.CheckConstraint(
                    condition=condition,
                    name="retry_amount_nonnegative",
                ),
                models.UniqueConstraint(
                    fields=unique_fields,
                    name="retry_parent_status_uniq",
                ),
            ],
        },
    )


def operation_states(operation):
    before = parent_state()
    after = before.clone()
    operation.state_forwards(APP_LABEL, after)
    return before, after


def create_parent_and_record(operation):
    before, after = operation_states(operation)
    parent = before.apps.get_model(APP_LABEL, "Parent")
    record = after.apps.get_model(APP_LABEL, "Record")
    with connection.schema_editor() as editor:
        editor.create_model(parent)
        editor.create_model(record)
    return before, after, parent, record


def drop_models(parent, record):
    with connection.schema_editor() as editor:
        editor.delete_model(record)
        editor.delete_model(parent)


@pytest.mark.django_db(transaction=True)
def test_existing_complete_model_is_safe_to_retry():
    operation = record_operation()
    before, after, parent, record = create_parent_and_record(operation)
    try:
        with connection.schema_editor() as editor:
            operation.database_forwards(APP_LABEL, editor, before, after)
    finally:
        drop_models(parent, record)


@pytest.mark.django_db(transaction=True)
def test_existing_model_with_wrong_column_type_fails_closed():
    actual = record_operation(code_length=16)
    _, _, parent, record = create_parent_and_record(actual)
    expected = record_operation(code_length=32)
    before, after = operation_states(expected)
    try:
        with pytest.raises(SchemaRetryError, match="type differs"):
            with connection.schema_editor() as editor:
                expected.database_forwards(APP_LABEL, editor, before, after)
    finally:
        drop_models(parent, record)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("actual_options", "error"),
    [
        ({"amount_null": False}, "nullability differs"),
        ({"amount_digits": 8}, "type differs|precision and scale"),
        ({"index_fields": ("status",)}, "columns differ"),
        ({"unique_fields": ("code", "status")}, "columns differ"),
    ],
)
def test_existing_model_with_narrower_or_wider_schema_fails_closed(actual_options, error):
    actual = record_operation(**actual_options)
    _, _, parent, record = create_parent_and_record(actual)
    expected = record_operation(
        amount_digits=9 if "amount_digits" in actual_options else None
    )
    before, after = operation_states(expected)
    try:
        with pytest.raises(SchemaRetryError, match=error):
            with connection.schema_editor() as editor:
                expected.database_forwards(APP_LABEL, editor, before, after)
    finally:
        drop_models(parent, record)


@pytest.mark.django_db(transaction=True)
def test_existing_model_with_missing_declared_index_fails_closed():
    actual = record_operation(include_index=False)
    _, _, parent, record = create_parent_and_record(actual)
    expected = record_operation(include_index=True)
    before, after = operation_states(expected)
    try:
        with pytest.raises(SchemaRetryError, match="retry_parent_amount_idx"):
            with connection.schema_editor() as editor:
                expected.database_forwards(APP_LABEL, editor, before, after)
    finally:
        drop_models(parent, record)


@pytest.mark.django_db(transaction=True)
def test_existing_model_with_wrong_check_definition_fails_closed():
    actual = record_operation(check="lte")
    _, _, parent, record = create_parent_and_record(actual)
    expected = record_operation(check="gte")
    before, after = operation_states(expected)
    try:
        with pytest.raises(SchemaRetryError, match="definition differs"):
            with connection.schema_editor() as editor:
                expected.database_forwards(APP_LABEL, editor, before, after)
    finally:
        drop_models(parent, record)


@pytest.mark.django_db(transaction=True)
def test_existing_model_with_wrong_foreign_key_target_fails_closed():
    before = ProjectState()
    for name, table in (("Parent", PARENT_TABLE), ("OtherParent", "schema_retry_other_parent")):
        before.add_model(
            ModelState(
                APP_LABEL,
                name,
                [("id", models.BigAutoField(primary_key=True))],
                {"db_table": table},
            )
        )

    def child_operation(target):
        return CreateModelIfCompatible(
            name="Child",
            fields=[
                ("id", models.BigAutoField(primary_key=True)),
                (
                    "parent",
                    models.ForeignKey(on_delete=models.PROTECT, to=f"{APP_LABEL}.{target}"),
                ),
            ],
            options={"db_table": "schema_retry_child"},
        )

    actual = child_operation("otherparent")
    actual_state = before.clone()
    actual.state_forwards(APP_LABEL, actual_state)
    expected = child_operation("parent")
    expected_state = before.clone()
    expected.state_forwards(APP_LABEL, expected_state)
    parent = before.apps.get_model(APP_LABEL, "Parent")
    other_parent = before.apps.get_model(APP_LABEL, "OtherParent")
    child = actual_state.apps.get_model(APP_LABEL, "Child")
    with connection.schema_editor() as editor:
        editor.create_model(parent)
        editor.create_model(other_parent)
        editor.create_model(child)
    try:
        with pytest.raises(SchemaRetryError, match="foreign key"):
            with connection.schema_editor() as editor:
                expected.database_forwards(APP_LABEL, editor, before, expected_state)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(child)
            editor.delete_model(other_parent)
            editor.delete_model(parent)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("actual_field", "expected_field"),
    [
        (models.IntegerField(), models.PositiveIntegerField()),
        (models.PositiveIntegerField(), models.IntegerField()),
    ],
)
def test_implicit_column_checks_cannot_be_weakened_or_strengthened(
    actual_field, expected_field
):
    def operation(field):
        return CreateModelIfCompatible(
            name="CheckedValue",
            fields=[
                ("id", models.BigAutoField(primary_key=True)),
                ("value", field),
            ],
            options={"db_table": "schema_retry_checked_value"},
        )

    actual = operation(actual_field)
    actual_before = ProjectState()
    actual_after = actual_before.clone()
    actual.state_forwards(APP_LABEL, actual_after)
    actual_model = actual_after.apps.get_model(APP_LABEL, "CheckedValue")
    expected = operation(expected_field)
    expected_before = ProjectState()
    expected_after = expected_before.clone()
    expected.state_forwards(APP_LABEL, expected_after)
    with connection.schema_editor() as editor:
        editor.create_model(actual_model)
    try:
        with pytest.raises(SchemaRetryError):
            with connection.schema_editor() as editor:
                expected.database_forwards(
                    APP_LABEL, editor, expected_before, expected_after
                )
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(actual_model)


@pytest.mark.django_db(transaction=True)
def test_add_operations_apply_once_then_validate_the_existing_schema():
    before = parent_state()
    base_operation = migrations.CreateModel(
        name="Record",
        fields=[
            ("id", models.BigAutoField(primary_key=True)),
            ("code", models.CharField(max_length=32)),
        ],
        options={"db_table": RECORD_TABLE},
    )
    base_operation.state_forwards(APP_LABEL, before)
    base_model = before.apps.get_model(APP_LABEL, "Record")
    parent = before.apps.get_model(APP_LABEL, "Parent")
    with connection.schema_editor() as editor:
        editor.create_model(parent)
        editor.create_model(base_model)

    add_field = AddFieldIfCompatible(
        model_name="record",
        name="status",
        field=models.CharField(max_length=16, null=True),
    )
    with_field = before.clone()
    add_field.state_forwards(APP_LABEL, with_field)
    add_index = AddIndexIfCompatible(
        model_name="record",
        index=models.Index(fields=["status"], name="retry_status_idx"),
    )
    with_index = with_field.clone()
    add_index.state_forwards(APP_LABEL, with_index)
    add_constraint = AddConstraintIfCompatible(
        model_name="record",
        constraint=models.UniqueConstraint(
            fields=("code", "status"), name="retry_code_status_uniq"
        ),
    )
    complete = with_index.clone()
    add_constraint.state_forwards(APP_LABEL, complete)
    complete_model = complete.apps.get_model(APP_LABEL, "Record")

    try:
        with connection.schema_editor() as editor:
            add_field.database_forwards(APP_LABEL, editor, before, with_field)
            add_index.database_forwards(APP_LABEL, editor, with_field, with_index)
            add_constraint.database_forwards(APP_LABEL, editor, with_index, complete)
        with connection.schema_editor() as editor:
            add_field.database_forwards(APP_LABEL, editor, before, with_field)
            add_index.database_forwards(APP_LABEL, editor, with_field, with_index)
            add_constraint.database_forwards(APP_LABEL, editor, with_index, complete)
    finally:
        drop_models(parent, complete_model)


@pytest.mark.parametrize(
    "operation",
    [
        AddFieldIfCompatible("record", "status", models.CharField(max_length=16)),
        AddIndexIfCompatible("record", models.Index(fields=["status"], name="idx")),
        AddConstraintIfCompatible(
            "record", models.UniqueConstraint(fields=("status",), name="uniq")
        ),
        CreateModelIfCompatible("Record", [("id", models.AutoField(primary_key=True))]),
    ],
)
def test_retry_operations_are_explicitly_irreversible(operation):
    assert operation.reversible is False
    with pytest.raises(IrreversibleError):
        operation.database_backwards(APP_LABEL, None, None, None)


def test_sql_normalisation_preserves_expression_semantics_and_literals():
    assert _normalise_expression('( "amount" >= 0 )') == _normalise_expression(
        "`amount`>=0"
    )
    assert _normalise_expression("(a + b) * c") != _normalise_expression("a + b * c")
    assert _normalise_expression("a IS NULL") != _normalise_expression("aisnull")
    assert _normalise_expression("a AND b") != _normalise_expression("aandb")
    assert _normalise_expression("status = 'Ready Now'") != _normalise_expression(
        "status = 'ready now'"
    )


@pytest.mark.django_db(transaction=True)
def test_mysql_retries_the_real_finance_and_platform_migrations():
    if connection.vendor != "mysql":
        pytest.skip("MySQL-only replay of already-applied production migrations")

    executor = MigrationExecutor(connection)
    migration_names = [
        ("finance", "0010_exchangerate_source_and_entered_by"),
        ("platform", "0007_usage_and_entitlements"),
        ("platform", "0008_trial_credit_and_period_index"),
        ("platform", "0009_platform_control_audit"),
        ("platform", "0010_cluster_config_version"),
        ("platform", "0011_cluster_health_observation"),
        ("platform", "0012_workspaceplatformprofile_placement_fence_and_more"),
        ("platform", "0013_workspacedatasnapshot"),
    ]
    for app_label, migration_name in migration_names:
        migration = executor.loader.get_migration(app_label, migration_name)
        node = executor.loader.graph.node_map[(app_label, migration_name)]
        state = executor.loader.project_state([parent.key for parent in node.parents])
        for sequence, operation in enumerate(migration.operations):
            previous_state = state.clone()
            operation.state_forwards(app_label, state)
            model_name = getattr(operation, "model_name", None) or operation.name
            fixture_state = state.clone()
            model_state = fixture_state.models[(app_label, model_name.lower())]
            tag = f"sr_{app_label[:2]}_{migration_name[:4]}_{sequence}"
            model_state.options["db_table"] = f"{tag}_{model_name.lower()}"
            model_state.options["indexes"] = deepcopy(
                model_state.options.get("indexes", [])
            )
            model_state.options["constraints"] = deepcopy(
                model_state.options.get("constraints", [])
            )
            for index in model_state.options.get("indexes", []):
                index.name = f"{tag}_{index.name}"
            for constraint in model_state.options.get("constraints", []):
                constraint.name = f"{tag}_{constraint.name}"
            fixture_state.reload_model(app_label, model_name.lower())
            fixture_operation = operation
            if isinstance(operation, AddIndexIfCompatible):
                fixture_index = deepcopy(operation.index)
                fixture_index.name = f"{tag}_{fixture_index.name}"
                fixture_operation = AddIndexIfCompatible(
                    operation.model_name, fixture_index
                )
            elif isinstance(operation, AddConstraintIfCompatible):
                fixture_constraint = deepcopy(operation.constraint)
                fixture_constraint.name = f"{tag}_{fixture_constraint.name}"
                fixture_operation = AddConstraintIfCompatible(
                    operation.model_name, fixture_constraint
                )

            fixture_model = fixture_state.apps.get_model(app_label, model_name)
            with connection.schema_editor() as editor:
                editor.create_model(fixture_model)
            try:
                with connection.schema_editor() as editor:
                    if (
                        isinstance(fixture_operation, AddConstraintIfCompatible)
                        and operation.constraint.name
                        == "plat_place_one_active_per_workspace"
                    ):
                        assert (
                            fixture_operation.constraint.create_sql(
                                fixture_model, editor
                            )
                            is None
                        )
                        with connection.cursor() as cursor:
                            constraints = connection.introspection.get_constraints(
                                cursor, fixture_model._meta.db_table
                            )
                        assert fixture_operation.constraint.name not in constraints
                    fixture_operation.database_forwards(
                        app_label, editor, previous_state, fixture_state
                    )
            finally:
                with connection.schema_editor() as editor:
                    editor.delete_model(fixture_model)
