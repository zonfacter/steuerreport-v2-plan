from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentId = Literal["coordinator", "import_sources", "crypto_forensics", "wallet_fifo", "tax_rewards", "valuation", "documentation"]


class AgentModels(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    local: str = Field(default="", max_length=256)
    openrouter: str = Field(default="", max_length=256)
    cloud: str = Field(default="", max_length=256)

    @model_validator(mode="after")
    def safe_ids(self):
        if any(any(ord(char) < 32 for char in value) for value in self.model_dump().values()):
            raise ValueError("agent_model_invalid")
        return self


class AiAgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agent_id: AgentId
    name: str = Field(min_length=3, max_length=100)
    instructions: str = Field(min_length=20, max_length=6000)
    enabled: bool = True
    models: AgentModels = Field(default_factory=AgentModels)


class AiAgentsStatus(BaseModel):
    revision: str
    profiles: list[AiAgentProfile]
    knowledge: dict
    knowledge_sha256: str


class AiAgentsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    profiles: list[AiAgentProfile] = Field(min_length=7, max_length=7)
