from __future__ import annotations

import json
from typing import Any

from backend.models.project import Project
from backend.workflows.types import WorkflowDefinition

_WORKFLOWS: dict[str, WorkflowDefinition] = {
    "generic_detection": WorkflowDefinition(
        key="generic_detection",
        display_name="通用目标检测",
        description="默认检测工作流：LLM grounding 产出 bbox，支持手工框编辑、导出与评估。",
        task_type="detection",
        task_family="bbox",
        supports_auto_annotation=True,
        supports_manual_bbox=True,
        supports_point_refine=False,
        capabilities=("llm_grounding", "manual_bbox_edit", "postprocess", "evaluation_adapter"),
    ),
    "generic_instance_segmentation": WorkflowDefinition(
        key="generic_instance_segmentation",
        display_name="通用实例分割",
        description="默认实例分割工作流：LLM grounding 产出 bbox，再由 SAM refine 生成 polygon/mask。",
        task_type="segmentation",
        task_family="instance_mask",
        supports_auto_annotation=True,
        supports_manual_bbox=True,
        supports_point_refine=True,
        capabilities=(
            "llm_grounding",
            "sam_refine",
            "manual_bbox_edit",
            "point_refine",
            "postprocess",
            "evaluation_adapter",
        ),
    ),
}

_DEFAULT_WORKFLOW_KEYS_BY_TASK_TYPE = {
    "detection": "generic_detection",
    "segmentation": "generic_instance_segmentation",
}


def list_available_workflows() -> list[WorkflowDefinition]:
    return list(_WORKFLOWS.values())


def get_workflow_definition(workflow_key: str) -> WorkflowDefinition:
    key = str(workflow_key or "").strip()
    if key not in _WORKFLOWS:
        available = ", ".join(sorted(_WORKFLOWS))
        raise ValueError(f"unknown workflow_key: {key or '<empty>'}; available workflows: {available}")
    return _WORKFLOWS[key]


def default_workflow_key_for_task_type(task_type: str) -> str:
    normalized = str(task_type or "").strip().lower()
    if normalized not in _DEFAULT_WORKFLOW_KEYS_BY_TASK_TYPE:
        available = ", ".join(sorted(_DEFAULT_WORKFLOW_KEYS_BY_TASK_TYPE))
        raise ValueError(f"unknown task_type: {task_type!r}; expected one of: {available}")
    return _DEFAULT_WORKFLOW_KEYS_BY_TASK_TYPE[normalized]


def validate_workflow_key_for_task_type(workflow_key: str, task_type: str) -> WorkflowDefinition:
    workflow = get_workflow_definition(workflow_key)
    normalized_task_type = str(task_type or "").strip().lower()
    if workflow.task_type != normalized_task_type:
        raise ValueError(
            f"workflow_key {workflow.key!r} is not compatible with task_type {normalized_task_type!r}"
        )
    return workflow


def resolve_project_workflow_key(
    project: Project | None,
    *,
    project_settings: dict[str, Any] | None = None,
    strict: bool = False,
) -> str:
    if isinstance(project_settings, dict):
        candidate = str(project_settings.get("workflow_key") or "").strip()
        if candidate:
            try:
                return get_workflow_definition(candidate).key
            except ValueError:
                if strict:
                    raise

    if project is not None and project.config:
        try:
            loaded = json.loads(project.config)
            if isinstance(loaded, dict):
                candidate = str(loaded.get("workflow_key") or "").strip()
                if candidate:
                    try:
                        return get_workflow_definition(candidate).key
                    except ValueError:
                        if strict:
                            raise
        except Exception:
            if strict:
                raise

    task_type = str(getattr(project, "task_type", "") or "").strip().lower()
    if not task_type:
        task_type = "detection"
    return default_workflow_key_for_task_type(task_type)


def resolve_project_workflow(
    project: Project | None,
    *,
    project_settings: dict[str, Any] | None = None,
    strict: bool = False,
) -> WorkflowDefinition:
    workflow_key = resolve_project_workflow_key(project, project_settings=project_settings, strict=strict)
    return get_workflow_definition(workflow_key)
