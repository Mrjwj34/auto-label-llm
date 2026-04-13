from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TaskFamily = Literal["bbox", "instance_mask", "semantic_mask", "polyline", "change_mask"]
LegacyTaskType = Literal["detection", "segmentation"]


@dataclass(frozen=True)
class WorkflowDefinition:
    key: str
    display_name: str
    description: str
    task_type: LegacyTaskType
    task_family: TaskFamily
    supports_auto_annotation: bool
    supports_manual_bbox: bool
    supports_point_refine: bool
    capabilities: tuple[str, ...]

    def has_capability(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "task_type": self.task_type,
            "task_family": self.task_family,
            "supports_auto_annotation": self.supports_auto_annotation,
            "supports_manual_bbox": self.supports_manual_bbox,
            "supports_point_refine": self.supports_point_refine,
            "capabilities": list(self.capabilities),
        }
