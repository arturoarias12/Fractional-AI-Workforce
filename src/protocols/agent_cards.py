"""Registry-facing Agent Card placeholder contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class RoleType(StrEnum):
    MANAGER = "manager"
    SPECIALIST = "specialist"


@dataclass(frozen=True, slots=True)
class AgentCard:
    schema_version: str
    agent_id: str
    display_name: str
    description: str
    version: str
    role_type: RoleType
    hireable: bool
    implementation_status: str
    input_contract: str
    output_contract: str
    capabilities: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    owner: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentCard":
        return cls(
            schema_version=str(value["schema_version"]),
            agent_id=str(value["agent_id"]),
            display_name=str(value["display_name"]),
            description=str(value["description"]),
            version=str(value["version"]),
            role_type=RoleType(value["role_type"]),
            hireable=bool(value["hireable"]),
            implementation_status=str(value["implementation_status"]),
            input_contract=str(value["input_contract"]),
            output_contract=str(value["output_contract"]),
            capabilities=tuple(value.get("capabilities", ())),
            required_dependencies=tuple(
                value.get("required_dependencies", ())
            ),
            owner=str(value["owner"]),
        )
