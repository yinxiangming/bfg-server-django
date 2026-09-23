"""Workspace business-data archive contract and the local SQLite-test adapter.

This module intentionally owns only the data-plane boundary.  Platform control
plane configuration exports remain in ``console_views.py`` and must not be
treated as business-data migrations.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import FileField
from django.utils import timezone

from bfg.common.storage import private_media_storage


ARCHIVE_FORMAT = "bfg.workspace-data.v1"
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_.-]+")
_EXCLUDED_LABELS = {
    "common.workspace",
    "common.user",
    "common.apikey",
    "platform.platformauditevent",
    "platform.platformactionrequest",
    "platform.workspaceoperation",
    "platform.workspacedatasnapshot",
    "platform.workspaceplatformprofile",
    "platform.platformmembership",
    "platform.platformssocode",
}
_REPLACEABLE_TARGET_LABELS = {"common.settings"}
_SECRET_FIELD_PARTS = ("password", "secret", "token", "credential", "private_key")


class DataPlaneError(Exception):
    """Base exception for a refused or failed data-plane operation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DataPlaneBoundaryError(DataPlaneError):
    """Raised when an operation is outside the local adapter's safe boundary."""


class DataPlaneIntegrityError(DataPlaneError):
    """Raised when an archive or target fails integrity validation."""


@dataclass(frozen=True)
class DataPlaneResult:
    """Stable, public-safe result returned by adapter operations."""

    manifest: dict[str, Any]
    artifact_uri: str
    artifact_sha256: str
    manifest_sha256: str
    row_count: int
    media_count: int
    media_bytes: int


class WorkspaceDataPlaneAdapter(ABC):
    """Contract implemented by a cluster-local data-plane adapter.

    ``export``, ``validate`` and ``restore`` are the first safe capability.  A
    remote adapter must add authenticated transport and resumable checkpoints
    before implementing ``cutover`` or ``rollback``.  The base methods refuse
    those actions so a caller cannot accidentally claim a migration occurred.
    """

    @abstractmethod
    def export(self, workspace, *, snapshot_id: str | None = None) -> DataPlaneResult:
        raise NotImplementedError

    @abstractmethod
    def validate(self, artifact_uri: str, *, expected_workspace_uuid=None) -> DataPlaneResult:
        raise NotImplementedError

    @abstractmethod
    def restore(self, artifact_uri: str, *, target_workspace) -> DataPlaneResult:
        raise NotImplementedError

    def cutover(self, *args, **kwargs):
        raise DataPlaneBoundaryError(
            "cutover_not_implemented",
            "Cluster cutover requires a remote coordinator and an explicit maintenance window.",
        )

    def rollback(self, *args, **kwargs):
        raise DataPlaneBoundaryError(
            "rollback_not_implemented",
            "Cross-cluster rollback is not available until the cutover journal is implemented.",
        )


def _json_value(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _redact_nested(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if any(part in normalized for part in _SECRET_FIELD_PARTS) or normalized.endswith("_api_key"):
                result[key] = None
            else:
                result[key] = _redact_nested(item)
        return result
    if isinstance(value, list):
        return [_redact_nested(item) for item in value]
    return value


def _is_secret_field(field_name: str) -> bool:
    normalized = field_name.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_FIELD_PARTS) or normalized.endswith("_api_key")


def _workspace_field(model):
    try:
        field = model._meta.get_field("workspace")
    except Exception:
        return None
    remote_model = getattr(field.remote_field, "model", None)
    if remote_model is None:
        return None
    return field if getattr(remote_model._meta, "label_lower", "") == "common.workspace" else None


def _model_label(model):
    return model._meta.label_lower


def _archive_name(label: str) -> str:
    return _SAFE_NAME.sub("_", label)


def _model_queryset(model, workspace):
    manager = getattr(model, "all_objects", None) or model._base_manager
    scope_path = _workspace_scope_path(model)
    return manager.filter(**{scope_path: workspace.pk}).order_by(model._meta.pk.name)


def _workspace_scope_path(model, visiting=None):
    """Return a safe ORM path for rows owned by a workspace.

    Direct ``workspace`` foreign keys are preferred.  A dependent model such as
    ProductVariant or MediaLink is included when it reaches a direct workspace
    model through a normal foreign key.  GenericForeignKey-only ownership is
    intentionally excluded until it has an explicit adapter declaration.
    """
    direct = _workspace_field(model)
    if direct is not None:
        return "workspace_id"
    visiting = set(visiting or ())
    label = _model_label(model)
    if label in visiting:
        return None
    visiting.add(label)
    for field in model._meta.concrete_fields:
        remote_model = getattr(field.remote_field, "model", None)
        if remote_model is None or remote_model is model:
            continue
        nested = _workspace_scope_path(remote_model, visiting)
        if nested:
            return f"{field.name}__{nested}"
    return None


def _candidate_models():
    models = []
    for model in apps.get_models():
        label = _model_label(model)
        if (
            model._meta.abstract
            or model._meta.proxy
            or model._meta.auto_created
            or model._meta.app_label == "platform"
            or label in _EXCLUDED_LABELS
            or _workspace_scope_path(model) is None
        ):
            continue
        models.append(model)
    return sorted(models, key=_model_label)


def _ordered_models(models):
    selected = {_model_label(model): model for model in models}
    dependencies = {label: set() for label in selected}
    for label, model in selected.items():
        for field in model._meta.concrete_fields:
            remote_model = getattr(field.remote_field, "model", None)
            remote_label = getattr(getattr(remote_model, "_meta", None), "label_lower", "")
            if remote_label in selected and remote_label != label:
                dependencies[label].add(remote_label)
    ordered = []
    while dependencies:
        ready = sorted(label for label, deps in dependencies.items() if not deps)
        if not ready:
            # Nullable/self-referential cycles can be inserted safely in the
            # same deterministic order; database FK checks still reject unsafe data.
            ready = [sorted(dependencies)[0]]
        for label in ready:
            ordered.append(selected[label])
            dependencies.pop(label)
        for deps in dependencies.values():
            deps.difference_update(ready)
    return ordered


class LocalWorkspaceDataPlaneAdapter(WorkspaceDataPlaneAdapter):
    """Archive and restore workspace rows and files on one Django deployment.

    This adapter is designed for local isolated-database tests and controlled
    operator archives.  It does not perform network transfer, DNS changes, source
    deletion, or an online cutover.
    """

    def __init__(self, archive_root=None):
        configured = archive_root or getattr(settings, "WORKSPACE_DATA_ARCHIVE_ROOT", "")
        self.archive_root = Path(configured or (Path(settings.MEDIA_ROOT).parent / "workspace-data-archives"))

    def _rows(self, model, workspace, temp_root):
        label = _model_label(model)
        rows = []
        files = []
        path = Path(temp_root) / "db" / f"{_archive_name(label)}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as output:
            for instance in _model_queryset(model, workspace).iterator():
                fields = {}
                for field in model._meta.concrete_fields:
                    if field.primary_key:
                        continue
                    if _is_secret_field(field.name):
                        continue
                    value = getattr(instance, field.attname)
                    if isinstance(field, FileField):
                        value = str(value or "")
                        if value:
                            storage = self._storage(instance, field)
                            if not storage.exists(value):
                                raise DataPlaneIntegrityError(
                                    "media_missing",
                                    "A workspace media reference has no backing object.",
                                )
                            archive_path = f"files/{_archive_name(label)}/{instance.pk}/{_archive_name(field.name)}"
                            file_path = Path(temp_root) / archive_path
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            with storage.open(value, "rb") as source, file_path.open("wb") as target:
                                target.write(source.read())
                            digest, size = _sha256_file(file_path)
                            files.append({
                                "model": label,
                                "pk": str(instance.pk),
                                "field": field.name,
                                "name": value,
                                "archive_path": archive_path,
                                "sha256": digest,
                                "size": size,
                            })
                    fields[field.attname] = _redact_nested(_json_value(value))
                row = {"pk": _json_value(instance.pk), "fields": fields}
                output.write(json.dumps(row, cls=DjangoJSONEncoder, sort_keys=True) + "\n")
                rows.append(row)
        digest, size = _sha256_file(path)
        return {
            "model": label,
            "path": str(path.relative_to(temp_root)),
            "sha256": digest,
            "size": size,
            "rows": len(rows),
        }, files

    def _storage(self, instance, field):
        if _model_label(instance.__class__) == "common.media" and getattr(instance, "is_sensitive", False):
            return private_media_storage()
        return field.storage

    def _restore_storage(self, model, field, values):
        if _model_label(model) == "common.media" and values.get("is_sensitive"):
            return private_media_storage()
        return field.storage

    def _read_archive(self, artifact_uri: str, *, expected_workspace_uuid=None):
        archive_path = self._resolve_artifact(artifact_uri)
        if not archive_path.exists():
            raise DataPlaneIntegrityError("artifact_missing", "The data-plane artifact is not available.")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                try:
                    manifest = json.loads(archive.read("manifest.json"))
                except (KeyError, json.JSONDecodeError) as exc:
                    raise DataPlaneIntegrityError("manifest_invalid", "The data-plane manifest is invalid.") from exc
                if not isinstance(manifest, dict):
                    raise DataPlaneIntegrityError("manifest_invalid", "The data-plane manifest is invalid.")
                if manifest.get("format") != ARCHIVE_FORMAT:
                    raise DataPlaneIntegrityError("format_unsupported", "The data-plane archive format is unsupported.")
                if expected_workspace_uuid and str(manifest.get("workspace_uuid")) != str(expected_workspace_uuid):
                    raise DataPlaneIntegrityError("workspace_mismatch", "The archive belongs to another workspace.")
                try:
                    for table in manifest.get("tables", []):
                        _verify_archive_member(archive, table["path"], table["sha256"])
                    for media in manifest.get("files", []):
                        _verify_archive_member(archive, media["archive_path"], media["sha256"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise DataPlaneIntegrityError("manifest_invalid", "The data-plane manifest is invalid.") from exc
        except DataPlaneIntegrityError:
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise DataPlaneIntegrityError("artifact_invalid", "The data-plane artifact is not a valid archive.") from exc
        digest, _ = _sha256_file(archive_path)
        manifest_bytes = json.dumps(manifest, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":")).encode()
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        return archive_path, manifest, digest, manifest_digest

    def _resolve_artifact(self, artifact_uri):
        path = Path(str(artifact_uri))
        if not path.is_absolute():
            path = self.archive_root / path
        try:
            path.resolve().relative_to(self.archive_root.resolve())
        except ValueError as exc:
            raise DataPlaneError("artifact_path_invalid", "The artifact path is outside the archive root.") from exc
        return path

    def export(self, workspace, *, snapshot_id: str | None = None) -> DataPlaneResult:
        self.archive_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="workspace-data-") as temp_root:
            tables = []
            files = []
            for model in _ordered_models(_candidate_models()):
                table, table_files = self._rows(model, workspace, temp_root)
                tables.append(table)
                files.extend(table_files)
            manifest = {
                "format": ARCHIVE_FORMAT,
                "version": 1,
                "workspace_uuid": str(workspace.uuid),
                "workspace_slug": workspace.slug,
                "exported_at": timezone.now().isoformat(),
                "database": {"vendor": workspace._state.db or "default"},
                "tables": tables,
                "files": files,
                "boundaries": {
                    "includes_business_data": True,
                    "includes_media": True,
                    "includes_global_identity": False,
                    "includes_platform_control_plane": False,
                    "source_cleanup": False,
                    "cluster_cutover": False,
                },
            }
            manifest_bytes = json.dumps(manifest, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":")).encode()
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            name = f"{workspace.uuid}/{snapshot_id or timezone.now().strftime('%Y%m%dT%H%M%S%f')}.zip"
            destination = self.archive_root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", manifest_bytes)
                for source in Path(temp_root).rglob("*"):
                    if source.is_file():
                        archive.write(source, source.relative_to(temp_root).as_posix())
        artifact_digest, _ = _sha256_file(destination)
        return DataPlaneResult(
            manifest=manifest,
            artifact_uri=str(destination.relative_to(self.archive_root)),
            artifact_sha256=artifact_digest,
            manifest_sha256=manifest_digest,
            row_count=sum(table["rows"] for table in manifest["tables"]),
            media_count=len(manifest["files"]),
            media_bytes=sum(item["size"] for item in manifest["files"]),
        )

    def validate(self, artifact_uri: str, *, expected_workspace_uuid=None) -> DataPlaneResult:
        archive_path, manifest, artifact_digest, manifest_digest = self._read_archive(
            artifact_uri, expected_workspace_uuid=expected_workspace_uuid,
        )
        return DataPlaneResult(
            manifest=manifest,
            artifact_uri=str(archive_path.relative_to(self.archive_root)),
            artifact_sha256=artifact_digest,
            manifest_sha256=manifest_digest,
            row_count=sum(table["rows"] for table in manifest.get("tables", [])),
            media_count=len(manifest.get("files", [])),
            media_bytes=sum(item["size"] for item in manifest.get("files", [])),
        )

    def _model_map(self, manifest):
        available = {_model_label(model): model for model in _candidate_models()}
        missing = sorted({table["model"] for table in manifest.get("tables", [])} - set(available))
        if missing:
            raise DataPlaneIntegrityError("model_unavailable", "The target does not support the archive's data models.")
        return available

    def _validate_external_references(self, archive, manifest, model_map):
        """Fail clearly before writes when a target lacks a global reference."""
        for table in manifest.get("tables", []):
            model = model_map[table["model"]]
            for raw in archive.read(table["path"]).decode("utf-8").splitlines():
                row = json.loads(raw)
                fields = row["fields"]
                workspace_field = _workspace_field(model)
                for field in model._meta.concrete_fields:
                    if field is workspace_field or field.primary_key:
                        continue
                    remote_model = getattr(field.remote_field, "model", None)
                    if remote_model is None:
                        continue
                    remote_label = getattr(getattr(remote_model, "_meta", None), "label_lower", "")
                    source_id = fields.get(field.attname)
                    if source_id is None or remote_label in model_map:
                        continue
                    manager = getattr(remote_model, "all_objects", None) or remote_model._base_manager
                    if not manager.filter(pk=source_id).exists():
                        raise DataPlaneIntegrityError(
                            "external_reference_missing",
                            "The target is missing a required global identity or reference.",
                        )

    def _assert_target_empty(self, target_workspace, models):
        for model in models:
            if _model_label(model) in _REPLACEABLE_TARGET_LABELS:
                continue
            if _model_queryset(model, target_workspace).exists():
                raise DataPlaneBoundaryError(
                    "target_not_empty",
                    f"Phase-one restore only accepts an empty target workspace ({_model_label(model)}).",
                )

    def restore(self, artifact_uri: str, *, target_workspace) -> DataPlaneResult:
        archive_path, manifest, artifact_digest, manifest_digest = self._read_archive(artifact_uri)
        if str(manifest.get("workspace_uuid")) == str(target_workspace.uuid):
            raise DataPlaneBoundaryError("same_workspace_restore", "Restore requires a different target workspace.")
        model_map = self._model_map(manifest)
        ordered = _ordered_models([model_map[table["model"]] for table in manifest.get("tables", [])])
        self._assert_target_empty(target_workspace, ordered)
        file_map = {(item["model"], str(item["pk"]), item["field"]): item for item in manifest.get("files", [])}
        created_files = []
        id_maps = {}
        deferred_relations = []
        deferred_generic_relations = []
        with zipfile.ZipFile(archive_path) as archive:
            try:
                self._validate_external_references(archive, manifest, model_map)
                with transaction.atomic():
                    for model in ordered:
                        label = _model_label(model)
                        id_maps.setdefault(label, {})
                        table = next(item for item in manifest["tables"] if item["model"] == _model_label(model))
                        for raw in archive.read(table["path"]).decode("utf-8").splitlines():
                            row = json.loads(raw)
                            values = dict(row["fields"])
                            workspace_field = _workspace_field(model)
                            if workspace_field is not None:
                                values[workspace_field.attname] = target_workspace.pk
                            for field in model._meta.concrete_fields:
                                if field.primary_key or field is workspace_field:
                                    continue
                                remote_model = getattr(field.remote_field, "model", None)
                                remote_label = getattr(getattr(remote_model, "_meta", None), "label_lower", "")
                                source_id = values.get(field.attname)
                                if source_id is not None and remote_label in id_maps:
                                    mapped_id = id_maps[remote_label].get(str(source_id))
                                    if mapped_id is None:
                                        if not field.null:
                                            raise DataPlaneIntegrityError(
                                                "foreign_key_unresolved",
                                                "The archive contains a required relationship that cannot be restored.",
                                            )
                                        deferred_relations.append((label, row["pk"], field, str(source_id), remote_label))
                                        values[field.attname] = None
                                    else:
                                        values[field.attname] = mapped_id
                                if not isinstance(field, FileField):
                                    continue
                                media = file_map.get((_model_label(model), str(row["pk"]), field.name))
                                if not media:
                                    continue
                                contents = archive.read(media["archive_path"])
                                storage = self._restore_storage(model, field, values)
                                target_name = f"workspace-data/{target_workspace.uuid}/{media['name']}"
                                saved_name = storage.save(target_name, ContentFile(contents))
                                created_files.append((storage, saved_name))
                                values[field.attname] = saved_name
                            source_pk = str(row["pk"])
                            instance = model(**values)
                            existing = None
                            if label in _REPLACEABLE_TARGET_LABELS:
                                existing = _model_queryset(model, target_workspace).first()
                            if existing:
                                instance.pk = existing.pk
                                instance.save_base(raw=True, force_update=True)
                                id_maps[label][source_pk] = existing.pk
                            else:
                                instance.save_base(raw=True)
                                id_maps[label][source_pk] = instance.pk
                            if values.get("content_type_id") and values.get("object_id") is not None:
                                deferred_generic_relations.append(
                                    (
                                        label,
                                        source_pk,
                                        values["content_type_id"],
                                        values["object_id"],
                                    )
                                )
                    for label, source_pk, field, source_id, remote_label in deferred_relations:
                        target_pk = id_maps[remote_label].get(source_id)
                        if target_pk is None:
                            raise DataPlaneIntegrityError(
                                "foreign_key_unresolved",
                                "The archive contains a relationship that cannot be restored.",
                            )
                        model = model_map[label]
                        instance = model._base_manager.get(pk=id_maps[label][str(source_pk)])
                        setattr(instance, field.attname, target_pk)
                        instance.save_base(raw=True, force_update=True, update_fields=[field.attname])
                    from django.contrib.contenttypes.models import ContentType

                    for label, source_pk, content_type_id, source_object_id in deferred_generic_relations:
                        content_type = ContentType.objects.get(pk=content_type_id)
                        related_model = content_type.model_class()
                        related_label = getattr(getattr(related_model, "_meta", None), "label_lower", "")
                        if related_label == "common.workspace":
                            target_object_id = target_workspace.pk
                        elif related_label in id_maps:
                            target_object_id = id_maps[related_label].get(str(source_object_id))
                            if target_object_id is None:
                                raise DataPlaneIntegrityError(
                                    "generic_reference_unresolved",
                                    "The archive contains a generic relationship that cannot be restored.",
                                )
                        else:
                            continue
                        model = model_map[label]
                        instance = model._base_manager.get(pk=id_maps[label][str(source_pk)])
                        instance.object_id = target_object_id
                        instance.save_base(raw=True, force_update=True, update_fields=["object_id"])
            except Exception:
                for storage, name in created_files:
                    try:
                        storage.delete(name)
                    except Exception:
                        pass
                raise
        return DataPlaneResult(
            manifest=manifest,
            artifact_uri=str(archive_path.relative_to(self.archive_root)),
            artifact_sha256=artifact_digest,
            manifest_sha256=manifest_digest,
            row_count=sum(table["rows"] for table in manifest.get("tables", [])),
            media_count=len(manifest.get("files", [])),
            media_bytes=sum(item["size"] for item in manifest.get("files", [])),
        )


def _sha256_file(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verify_archive_member(archive, name, expected):
    try:
        contents = archive.read(name)
    except KeyError as exc:
        raise DataPlaneIntegrityError("member_missing", "The data-plane archive is incomplete.") from exc
    actual = hashlib.sha256(contents).hexdigest()
    if actual != expected:
        raise DataPlaneIntegrityError("checksum_mismatch", "The data-plane archive failed checksum validation.")


def get_data_plane_adapter(*, archive_root=None):
    """Return the explicitly supported local adapter.

    A future cluster adapter should be selected here only after authenticated
    transport and resumability are available; silently falling back to local
    storage for a remote Cluster would risk writing data to the wrong tenant.
    """

    return LocalWorkspaceDataPlaneAdapter(archive_root=archive_root)
