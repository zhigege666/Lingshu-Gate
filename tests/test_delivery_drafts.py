"""Private synthetic delivery draft persistence and revision contract."""
import pytest

from lingshu_gate.application.delivery_drafts import DeliveryDraftRequest, DeliveryDraftStore
from lingshu_gate.registry import ToolExecutionError


def test_draft_is_encrypted_persistent_user_isolated_and_revision_bound(tmp_path):
    store = DeliveryDraftStore(tmp_path)
    patch = {"launch": {"env": {"NODE_ENV": "synthetic-staging-marker", "API_TOKEN": "${credential:synthetic}"}}}
    result = store.save("upload-a", "operator-a", DeliveryDraftRequest(expected_revision=0, manifest_patch=patch))
    assert result["revision"] == 1
    assert "synthetic-staging-marker" not in (tmp_path / "credentials.json").read_text()
    assert DeliveryDraftStore(tmp_path).get("upload-a", "operator-a")["manifest_patch"] == patch
    assert store.get("upload-a", "operator-b")["revision"] == 0
    with pytest.raises(ToolExecutionError, match="Draft changed"):
        store.save("upload-a", "operator-a", DeliveryDraftRequest(expected_revision=0))
    assert store.get("upload-a", "operator-a")["revision"] == 1


def test_draft_rejects_secret_values_and_redacted_values(tmp_path):
    store = DeliveryDraftStore(tmp_path)
    for env in ({"API_TOKEN": "synthetic-secret"}, {"NODE_ENV": "***"}):
        with pytest.raises(ValueError):
            store.save("upload-a", "operator-a", DeliveryDraftRequest(expected_revision=0, manifest_patch={"launch": {"env": env}}))
    assert not (tmp_path / "credentials.json").exists()
