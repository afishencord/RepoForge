from __future__ import annotations

from app.main import app
from app import models


def test_mapped_annotations_are_python_39_safe_for_alembic() -> None:
    for model in (
        models.Bundle,
        models.RepoSource,
        models.GPGKey,
        models.BuildJob,
        models.User,
        models.AuditEvent,
        models.Artifact,
    ):
        for annotation in model.__annotations__.values():
            annotation_text = str(annotation)
            if annotation_text.startswith("Mapped["):
                assert "|" not in annotation_text


def test_route_annotations_are_python_39_safe_for_fastapi() -> None:
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        annotations = getattr(endpoint, "__annotations__", {})
        for annotation in annotations.values():
            assert "|" not in str(annotation)
