"""Fail-closed retry operations for interrupted schema migrations.

These operations are intentionally irreversible.  An interrupted deployment can
leave an object behind without a migration-recorder row; guessing that its shape
is safe would allow Django to record a migration against the wrong schema.
"""

import re
from dataclasses import dataclass

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


class SchemaRetryError(RuntimeError):
    """Raised when an existing database object is not the declared object."""


class _IrreversibleRetryOperation:
    reversible = False

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        raise IrreversibleError(
            "Schema retry migrations cannot be reversed because an existing "
            "object may predate the interrupted migration."
        )


@dataclass(frozen=True)
class _Column:
    db_type: str
    null: bool
    primary_key: bool
    auto_increment: bool


def _fail(table, detail):
    raise SchemaRetryError(
        f"Existing table {table!r} is incompatible with this migration: {detail}"
    )


def _normalise_type(value):
    value = re.sub(r"\s+", " ", str(value or "").strip().lower())
    value = re.sub(r"\s*([(),])\s*", r"\1", value)
    value = value.replace(" auto_increment", "")
    value = {"bool": "tinyint(1)", "double precision": "double"}.get(value, value)
    value = re.sub(r"^integer(?=\b|\()", "int", value)
    return re.sub(r"^numeric(?=\b|\()", "decimal", value)


def _sql_tokens(value):
    """Tokenize generated DDL while preserving operators and literal bytes."""
    value = str(value or "").strip()
    tokens = []
    position = 0
    two_character_operators = {">=", "<=", "<>", "!=", "==", "||", "&&", "::", "->"}
    punctuation = set("(),.+-*/%<>=:;")
    while position < len(value):
        char = value[position]
        if char.isspace():
            position += 1
            continue
        if char == "'":
            end = position + 1
            while end < len(value):
                if value[end] == "\\":
                    if end + 1 >= len(value):
                        raise SchemaRetryError("Cannot validate an unterminated SQL escape")
                    end += 2
                    continue
                if value[end] == "'":
                    if end + 1 < len(value) and value[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    tokens.append(value[position:end])
                    position = end
                    break
                end += 1
            else:
                raise SchemaRetryError("Cannot validate an unterminated SQL literal")
            continue
        if char in {'`', '"', "["}:
            closing = "]" if char == "[" else char
            end = value.find(closing, position + 1)
            if end < 0:
                raise SchemaRetryError("Cannot validate an unterminated SQL identifier")
            identifier = value[position + 1 : end]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", identifier):
                raise SchemaRetryError(f"Cannot validate SQL identifier {identifier!r}")
            tokens.append(identifier.lower())
            position = end + 1
            continue
        identifier = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", value[position:])
        if identifier:
            token = identifier.group(0)
            tokens.append(token.lower())
            position += len(token)
            continue
        number = re.match(r"\d+(?:\.\d+)?", value[position:])
        if number:
            token = number.group(0)
            tokens.append(token)
            position += len(token)
            continue
        operator = value[position : position + 2]
        if operator in two_character_operators:
            tokens.append(operator)
            position += 2
            continue
        if char in punctuation:
            tokens.append(char)
            position += 1
            continue
        raise SchemaRetryError(f"Cannot validate unsupported SQL token {char!r}")
    if tokens and tokens[-1] == ";":
        tokens.pop()
    return tokens


def _normalise_sql(value):
    return "\x1f".join(_sql_tokens(value))


def _normalise_expression(value):
    tokens = _sql_tokens(value)
    while tokens[:1] == ["("] and tokens[-1:] == [")"]:
        depth = 0
        closes_at_end = False
        for position, token in enumerate(tokens):
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = position == len(tokens) - 1
                    break
        if not closes_at_end:
            break
        tokens = tokens[1:-1]
    return "\x1f".join(tokens)


def _normalise_fk_rule(value):
    value = str(value or "").upper()
    return "NO ACTION" if value == "RESTRICT" else value


def _columns(schema_editor, table):
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA table_xinfo({quote(table)})")
            return {
                row[1]: _Column(
                    _normalise_type(row[2]),
                    not bool(row[3] or row[5]),
                    bool(row[5]),
                    False,
                )
                for row in cursor.fetchall()
                if not row[6]
            }
        if connection.vendor == "mysql":
            cursor.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, EXTRA "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                [table],
            )
            return {
                name: _Column(
                    _normalise_type(column_type),
                    is_nullable == "YES",
                    column_key == "PRI",
                    "auto_increment" in (extra or "").lower(),
                )
                for name, column_type, is_nullable, column_key, extra in cursor.fetchall()
            }
    _fail(table, f"database backend {connection.vendor!r} is not supported")


def _constraints(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(cursor, table)


def _column_names(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(
                cursor, table
            )
        }


def _foreign_keys(schema_editor, table):
    connection = schema_editor.connection
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        if connection.vendor == "sqlite":
            cursor.execute(f"PRAGMA foreign_key_list({quote(table)})")
            return {
                row[3]: {
                    "target": (row[2], row[4]),
                    "on_update": row[5].upper(),
                    "on_delete": row[6].upper(),
                }
                for row in cursor.fetchall()
            }
        if connection.vendor == "mysql":
            cursor.execute(
                "SELECT k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, "
                "k.REFERENCED_COLUMN_NAME, r.UPDATE_RULE, r.DELETE_RULE "
                "FROM information_schema.KEY_COLUMN_USAGE k "
                "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
                "ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
                "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
                "AND r.TABLE_NAME = k.TABLE_NAME "
                "WHERE k.TABLE_SCHEMA = DATABASE() AND k.TABLE_NAME = %s "
                "AND k.REFERENCED_TABLE_NAME IS NOT NULL",
                [table],
            )
            return {
                column: {
                    "target": (target_table, target_column),
                    "on_update": update_rule.upper(),
                    "on_delete": delete_rule.upper(),
                }
                for column, target_table, target_column, update_rule, delete_rule in cursor.fetchall()
            }
    _fail(table, f"database backend {connection.vendor!r} is not supported")


def _expected_delete_rule(field):
    on_delete = field.remote_field.on_delete
    if on_delete in {
        models.CASCADE,
        models.SET_NULL,
        models.RESTRICT,
        models.PROTECT,
        models.DO_NOTHING,
        models.SET_DEFAULT,
    }:
        # Django enforces on_delete in the ORM. Its schema editors create
        # database foreign keys with NO ACTION for these built-in policies.
        return "NO ACTION"
    raise SchemaRetryError(
        f"Unsupported on_delete callable for {field.model._meta.label}.{field.name}"
    )


def _field_columns(model, names):
    return [model._meta.get_field(name.lstrip("-")).column for name in names]


def _matching(constraints, columns, flag):
    return [
        item
        for item in constraints.values()
        if list(item.get("columns", [])) == list(columns) and bool(item.get(flag))
    ]


def _has_implicit_field_index(
    constraints, column, allow_left_prefix=False, declared_unique_indexes=frozenset()
):
    for name, item in constraints.items():
        if not item.get("index"):
            continue
        columns = list(item.get("columns", []))
        if columns == [column] and not item.get("unique"):
            return True
        # MySQL can discard a redundant single-column foreign-key index once
        # a non-unique composite index has the same leftmost column. That index
        # provides the lookup shape requested by an implicit field db_index.
        if allow_left_prefix and len(columns) > 1 and columns[0] == column:
            if not item.get("unique"):
                return True
            if (name, tuple(columns)) in declared_unique_indexes:
                return True
    return False


def _declared_unique_indexes(schema_editor, model):
    declared = set()
    for constraint in model._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint):
            continue
        if (
            not constraint.fields
            or constraint.expressions
            or constraint.include
            or constraint.opclasses
            or constraint.condition is not None
        ):
            continue
        if constraint.create_sql(model, schema_editor) is None:
            continue
        declared.add((constraint.name, tuple(_field_columns(model, constraint.fields))))
    return declared


def _validate_field(schema_editor, model, field):
    table = model._meta.db_table
    column = _columns(schema_editor, table).get(field.column)
    if column is None:
        _fail(table, f"missing column {field.column!r}")
    expected_type = field.db_parameters(schema_editor.connection).get("type")
    if expected_type is None:
        _fail(table, f"column type for {field.column!r} is unsupported")
    if schema_editor.connection.vendor == "sqlite" and isinstance(field, models.DecimalField):
        _fail(
            table,
            f"SQLite cannot prove precision and scale for decimal column {field.column!r}",
        )
    expected_type = _normalise_type(expected_type)
    if column.db_type != expected_type:
        _fail(
            table,
            f"column {field.column!r} type differs "
            f"(expected {expected_type!r}, got {column.db_type!r})",
        )
    if column.null != bool(field.null):
        _fail(table, f"column {field.column!r} nullability differs")
    if column.primary_key != bool(field.primary_key):
        _fail(table, f"column {field.column!r} primary-key status differs")
    expected_auto = isinstance(
        field, (models.AutoField, models.BigAutoField, models.SmallAutoField)
    )
    if schema_editor.connection.vendor == "mysql" and column.auto_increment != expected_auto:
        _fail(table, f"column {field.column!r} auto-increment status differs")
    _validate_field_check(schema_editor, model, field)

    constraints = _constraints(schema_editor, table)
    if field.unique and not field.primary_key and not _matching(constraints, [field.column], "unique"):
        _fail(table, f"missing unique constraint for {field.column!r}")
    if field.db_index and not field.unique:
        allow_mysql_fk_prefix = (
            schema_editor.connection.vendor == "mysql"
            and field.remote_field
            and field.many_to_one
            and field.db_constraint
        )
        if not _has_implicit_field_index(
            constraints,
            field.column,
            allow_left_prefix=allow_mysql_fk_prefix,
            declared_unique_indexes=_declared_unique_indexes(schema_editor, model),
        ):
            _fail(table, f"missing non-unique index for {field.column!r}")

    if field.remote_field and field.many_to_one and field.db_constraint:
        actual = _foreign_keys(schema_editor, table).get(field.column)
        target = (field.target_field.model._meta.db_table, field.target_field.column)
        if not actual or actual["target"] != target:
            _fail(table, f"foreign key {field.column!r} differs")
        if _normalise_fk_rule(actual["on_delete"]) != _normalise_fk_rule(_expected_delete_rule(field)):
            _fail(table, f"foreign key {field.column!r} delete rule differs")
        if _normalise_fk_rule(actual["on_update"]) != "NO ACTION":
            _fail(table, f"foreign key {field.column!r} update rule differs")


def _index_definition(schema_editor, name):
    if schema_editor.connection.vendor != "sqlite":
        return None
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = %s", [name]
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _check_definitions(schema_editor, table):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if connection.vendor == "mysql":
            cursor.execute(
                "SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
                "FROM information_schema.CHECK_CONSTRAINTS cc "
                "JOIN information_schema.TABLE_CONSTRAINTS tc "
                "ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA "
                "AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
                "WHERE tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = %s "
                "AND tc.CONSTRAINT_TYPE = 'CHECK'",
                [table],
            )
            return {name: clause for name, clause in cursor.fetchall()}
        if connection.vendor == "sqlite":
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = %s",
                [table],
            )
            row = cursor.fetchone()
            return {"__table_sql__": row[0] if row else ""}
    _fail(table, f"database backend {connection.vendor!r} is not supported")


def _extract_named_check(table_sql, name):
    match = re.search(
        rf"constraint\s+[`\"\[]?{re.escape(name)}[`\"\]]?\s+check\s*\(",
        table_sql,
        re.IGNORECASE,
    )
    if not match:
        return None
    start = table_sql.find("(", match.start())
    depth = 0
    quote = None
    for position in range(start, len(table_sql)):
        char = table_sql[position]
        if quote:
            if char == quote and table_sql[position - 1] != "\\":
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return table_sql[start + 1 : position]
    return None


def _extract_checks(table_sql):
    clauses = []
    for match in re.finditer(r"\bcheck\s*\(", table_sql, re.IGNORECASE):
        start = table_sql.find("(", match.start())
        depth = 0
        quote = None
        position = start
        while position < len(table_sql):
            char = table_sql[position]
            if quote:
                if char == quote:
                    if position + 1 < len(table_sql) and table_sql[position + 1] == quote:
                        position += 1
                    else:
                        quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    clauses.append(table_sql[start + 1 : position])
                    break
            position += 1
    return clauses


def _actual_check_clauses(schema_editor, table):
    definitions = _check_definitions(schema_editor, table)
    if schema_editor.connection.vendor == "sqlite":
        return _extract_checks(definitions["__table_sql__"])
    return list(definitions.values())


def _field_check(field, connection):
    return field.db_parameters(connection).get("check")


def _validate_field_check(schema_editor, model, field):
    expected = _field_check(field, schema_editor.connection)
    if expected is None:
        return
    actual = {
        _normalise_expression(clause)
        for clause in _actual_check_clauses(schema_editor, model._meta.db_table)
    }
    if _normalise_expression(expected) not in actual:
        _fail(model._meta.db_table, f"column {field.column!r} check constraint differs")


def _validate_index(schema_editor, model, index):
    table = model._meta.db_table
    if (
        not index.fields
        or index.expressions
        or index.include
        or index.opclasses
        or index.condition
    ):
        _fail(table, f"index {index.name!r} uses unsupported validation features")
    actual = _constraints(schema_editor, table).get(index.name)
    if not actual or not actual.get("index") or actual.get("unique"):
        _fail(table, f"missing non-unique index {index.name!r}")
    if list(actual.get("columns", [])) != _field_columns(model, index.fields):
        _fail(table, f"index {index.name!r} columns differ")
    expected_orders = ["DESC" if name.startswith("-") else "ASC" for name in index.fields]
    if "orders" in actual and list(actual["orders"]) != expected_orders:
        _fail(table, f"index {index.name!r} column ordering differs")
    if actual.get("type", models.Index.suffix) != models.Index.suffix:
        _fail(table, f"index {index.name!r} type differs")


def _validate_constraint(schema_editor, model, constraint):
    table = model._meta.db_table
    expected_sql = constraint.create_sql(model, schema_editor)
    constraints = _constraints(schema_editor, table)
    if expected_sql is None:
        if constraint.name in constraints:
            _fail(table, f"unsupported constraint {constraint.name!r} unexpectedly exists")
        return
    actual = constraints.get(constraint.name)

    if isinstance(constraint, models.UniqueConstraint):
        if constraint.expressions or constraint.include or constraint.opclasses:
            _fail(table, f"unique constraint {constraint.name!r} is unsupported")
        if not actual or not actual.get("unique"):
            _fail(table, f"missing unique constraint {constraint.name!r}")
        if list(actual.get("columns", [])) != _field_columns(model, constraint.fields):
            _fail(table, f"unique constraint {constraint.name!r} columns differ")
        if constraint.condition is not None:
            definition = _index_definition(schema_editor, constraint.name)
            if definition is None or _normalise_sql(definition) != _normalise_sql(expected_sql):
                _fail(table, f"conditional unique constraint {constraint.name!r} differs")
        return

    if isinstance(constraint, models.CheckConstraint):
        if not actual or not actual.get("check"):
            _fail(table, f"missing check constraint {constraint.name!r}")
        expected_clause = constraint._get_check_sql(model, schema_editor)
        definitions = _check_definitions(schema_editor, table)
        if schema_editor.connection.vendor == "sqlite":
            clause = _extract_named_check(definitions["__table_sql__"], constraint.name)
        else:
            clause = definitions.get(constraint.name)
        if clause is None or _normalise_expression(clause) != _normalise_expression(expected_clause):
            _fail(table, f"check constraint {constraint.name!r} definition differs")
        return

    _fail(table, f"constraint type {type(constraint).__name__!r} is not supported")


def _validate_model(schema_editor, model):
    table = model._meta.db_table
    actual_columns = set(_columns(schema_editor, table))
    expected_columns = {field.column for field in model._meta.local_fields}
    if actual_columns != expected_columns:
        _fail(table, f"column set differs: expected {sorted(expected_columns)!r}, got {sorted(actual_columns)!r}")
    for field in model._meta.local_fields:
        _validate_field(schema_editor, model, field)
    for index in model._meta.indexes:
        _validate_index(schema_editor, model, index)
    for constraint in model._meta.constraints:
        _validate_constraint(schema_editor, model, constraint)
    expected_checks = {
        _normalise_expression(check)
        for field in model._meta.local_fields
        if (check := _field_check(field, schema_editor.connection)) is not None
    }
    expected_checks.update(
        _normalise_expression(constraint._get_check_sql(model, schema_editor))
        for constraint in model._meta.constraints
        if isinstance(constraint, models.CheckConstraint)
        and constraint.create_sql(model, schema_editor) is not None
    )
    actual_checks = {
        _normalise_expression(clause)
        for clause in _actual_check_clauses(schema_editor, table)
    }
    if actual_checks != expected_checks:
        _fail(table, "check constraint set differs")


class AddFieldIfCompatible(_IrreversibleRetryOperation, migrations.AddField):
    """Add a field, or accept an existing field only after validation."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        field = model._meta.get_field(self.name)
        if field.column in _column_names(schema_editor, model._meta.db_table):
            if schema_editor.connection.vendor not in {"mysql", "sqlite"}:
                _fail(
                    model._meta.db_table,
                    f"existing column validation is unsupported for "
                    f"database backend {schema_editor.connection.vendor!r}",
                )
            _validate_field(schema_editor, model, field)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class CreateModelIfCompatible(_IrreversibleRetryOperation, migrations.CreateModel):
    """Create a model, or accept an existing table only after validation."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if model._meta.db_table in schema_editor.connection.introspection.table_names():
            _validate_model(schema_editor, model)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddIndexIfCompatible(_IrreversibleRetryOperation, migrations.AddIndex):
    """Add an index, or accept an existing index only after validation."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        actual = _constraints(schema_editor, model._meta.db_table).get(self.index.name)
        if actual:
            if schema_editor.connection.vendor not in {"mysql", "sqlite"}:
                _fail(
                    model._meta.db_table,
                    f"existing index validation is unsupported for "
                    f"database backend {schema_editor.connection.vendor!r}",
                )
            _validate_index(schema_editor, model, self.index)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class AddConstraintIfCompatible(_IrreversibleRetryOperation, migrations.AddConstraint):
    """Add a constraint, or accept it only after validating its definition."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        constraints = _constraints(schema_editor, model._meta.db_table)
        expected_sql = self.constraint.create_sql(model, schema_editor)
        if self.constraint.name in constraints or expected_sql is None:
            if schema_editor.connection.vendor not in {"mysql", "sqlite"}:
                _fail(
                    model._meta.db_table,
                    f"existing constraint validation is unsupported for "
                    f"database backend {schema_editor.connection.vendor!r}",
                )
            _validate_constraint(schema_editor, model, self.constraint)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)
