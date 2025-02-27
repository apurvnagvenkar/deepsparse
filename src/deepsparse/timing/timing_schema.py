# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass

from pydantic import BaseModel, Field


__all__ = ["InferenceTimingSchema", "InferencePhases"]


@dataclass(frozen=True)
class InferencePhases:
    PRE_PROCESS: str = "pre_process"
    ENGINE_FORWARD: str = "engine_forward"
    POST_PROCESS: str = "post_process"
    TOTAL_INFERENCE: str = "total_inference"


class InferenceTimingSchema(BaseModel):
    """
    Stores the information about time deltas
    (in seconds) of certain processes within
    the inference pipeline
    """

    pre_process: float = Field(
        description="The duration [in seconds] of "
        "the pre-processing step prior to inference"
    )
    engine_forward: float = Field(
        description="The duration [in seconds] of the "
        "neural network inference in the engine"
    )
    post_process: float = Field(
        description="The duration [in seconds] of the "
        "post-processing step following inference"
    )
    total_inference: float = Field(
        description="The total duration [in seconds] for "
        "the inference pipeline, end to end"
    )
