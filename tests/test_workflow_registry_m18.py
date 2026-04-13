from __future__ import annotations

import json

from backend.models.project import Project
from backend.workflows.registry import resolve_project_workflow, resolve_project_workflow_key


def test_legacy_project_defaults_to_workflow_from_task_type():
    detection_project = Project(id=1, name="det", task_type="detection", config=None)
    segmentation_project = Project(id=2, name="seg", task_type="segmentation", config=None)

    assert resolve_project_workflow_key(detection_project) == "generic_detection"
    assert resolve_project_workflow(segmentation_project).key == "generic_instance_segmentation"
    assert resolve_project_workflow(segmentation_project).supports_point_refine is True


def test_invalid_stored_workflow_falls_back_to_task_type_default():
    project = Project(
        id=1,
        name="legacy",
        task_type="segmentation",
        config=json.dumps({"workflow_key": "unknown_workflow"}, ensure_ascii=False),
    )

    workflow = resolve_project_workflow(project)
    assert workflow.key == "generic_instance_segmentation"
    assert workflow.task_family == "instance_mask"


def test_project_settings_response_exposes_workflow_metadata(client):
    create_resp = client.post("/api/projects", json={"name": "workflow-project", "task_type": "detection"})
    assert create_resp.status_code == 200
    project_id = int(create_resp.json()["data"]["id"])

    settings_resp = client.get(f"/api/projects/{project_id}/settings")
    assert settings_resp.status_code == 200

    payload = settings_resp.json()["data"]
    assert payload["workflow_key"] == "generic_detection"
    assert payload["task_family"] == "bbox"
    assert payload["workflow"]["key"] == "generic_detection"
    assert payload["workflow"]["supports_point_refine"] is False
    assert "workflow_key" in payload["_meta"]["project_editable_paths"]
    assert any(item["key"] == "generic_instance_segmentation" for item in payload["_meta"]["available_workflows"])


def test_project_meta_lists_available_workflows_and_defaults(client):
    resp = client.get("/api/projects/meta")
    assert resp.status_code == 200

    payload = resp.json()["data"]
    assert payload["task_types"] == ["detection", "segmentation"]
    assert payload["default_workflows"]["detection"] == "generic_detection"
    assert payload["default_workflows"]["segmentation"] == "generic_instance_segmentation"
    assert any(item["key"] == "generic_detection" for item in payload["workflows"])
    assert any(item["key"] == "generic_instance_segmentation" for item in payload["workflows"])


def test_create_project_accepts_workflow_key_and_rejects_incompatible_value(client):
    create_resp = client.post(
        "/api/projects",
        json={"name": "seg-workflow", "task_type": "segmentation", "workflow_key": "generic_instance_segmentation"},
    )
    assert create_resp.status_code == 200
    project_id = int(create_resp.json()["data"]["id"])

    settings_resp = client.get(f"/api/projects/{project_id}/settings")
    assert settings_resp.status_code == 200
    payload = settings_resp.json()["data"]
    assert payload["workflow_key"] == "generic_instance_segmentation"
    assert payload["task_family"] == "instance_mask"

    bad_create = client.post(
        "/api/projects",
        json={"name": "bad-workflow", "task_type": "detection", "workflow_key": "generic_instance_segmentation"},
    )
    assert bad_create.status_code == 400
    assert "not compatible" in bad_create.json()["message"]


def test_patch_project_settings_validates_workflow_compatibility(client):
    create_resp = client.post("/api/projects", json={"name": "workflow-patch", "task_type": "detection"})
    assert create_resp.status_code == 200
    project_id = int(create_resp.json()["data"]["id"])

    patch_resp = client.patch(
        f"/api/projects/{project_id}/settings",
        json={"workflow_key": "generic_detection"},
    )
    assert patch_resp.status_code == 200
    payload = patch_resp.json()["data"]["settings"]
    assert payload["workflow_key"] == "generic_detection"
    assert payload["task_family"] == "bbox"
    assert "workflow_key" in patch_resp.json()["data"]["change"]["other_paths"]

    bad_patch = client.patch(
        f"/api/projects/{project_id}/settings",
        json={"workflow_key": "generic_instance_segmentation"},
    )
    assert bad_patch.status_code == 400
    assert "not compatible" in bad_patch.json()["message"]


def test_list_projects_includes_workflow_key_and_task_family(client):
    create_resp = client.post(
        "/api/projects",
        json={"name": "listed-workflow", "task_type": "segmentation", "workflow_key": "generic_instance_segmentation"},
    )
    assert create_resp.status_code == 200

    list_resp = client.get("/api/projects")
    assert list_resp.status_code == 200
    row = next(item for item in list_resp.json()["data"] if item["name"] == "listed-workflow")
    assert row["task_type"] == "segmentation"
    assert row["workflow_key"] == "generic_instance_segmentation"
    assert row["task_family"] == "instance_mask"
