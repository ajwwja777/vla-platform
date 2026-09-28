#!/usr/bin/env python3
"""Loopback-only server entry for the Cobot DM0.5 adapter."""

from dataclasses import dataclass, field

from flask import Flask
import tyro

from dm05_cobot_sft import DM05Exp
from opendm.exp.dm05_exp import DM05ModelConfig
from opendm.model.dm05.dm05_arch import DM05Config, DM05ForConditionalGeneration
from server.local_model_config import (
    apply_cobot_local_attention_backends,
    validate_exact_weight_loading,
)


@dataclass
class LocalDM05ModelConfig(DM05ModelConfig):
    """Load immutable weights with compatible attention set before construction."""

    def _load_base_checkpoint_model(self) -> DM05ForConditionalGeneration:
        config = DM05Config.from_pretrained(self.model_name_or_path)
        for attribute, value in self._config_overrides().items():
            setattr(config, attribute, value)
        apply_cobot_local_attention_backends(config)
        model, loading_info = DM05ForConditionalGeneration.from_pretrained(
            self.model_name_or_path,
            config=config,
            torch_dtype=self._torch_dtype(),
            output_loading_info=True,
        )
        validate_exact_weight_loading(
            loading_info, tensor_count=len(model.state_dict())
        )
        return model


@dataclass
class LocalDM05Exp(DM05Exp):
    """Keep the official inference implementation but never expose it remotely."""

    model_config: LocalDM05ModelConfig = field(default_factory=LocalDM05ModelConfig)

    def inference(self) -> None:
        self._initialize_inference_runtime()
        app = Flask(__name__)
        app.add_url_rule(
            "/process_frame",
            "process_frame",
            self.inference_config._infer_legacy,
            methods=["POST"],
        )
        app.add_url_rule(
            "/v1/infer",
            "v1_infer",
            self.inference_config._infer,
            methods=["POST"],
        )
        app.run(
            host="127.0.0.1",
            port=self.inference_config.port,
            debug=False,
            threaded=False,
        )


if __name__ == "__main__":
    experiment = tyro.cli(LocalDM05Exp)
    if experiment.task != "inference":
        raise ValueError("Cobot-local entry only supports task=inference")
    experiment.inference()
