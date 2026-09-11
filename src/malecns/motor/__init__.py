"""MaleCNS motor/output population registries."""

from .registry import (
    descending_ids,
    forward_output_ids,
    stop_output_ids,
    turn_left_output_ids,
    turn_right_output_ids,
    walking_state_ids,
)
from .flight_decoder import FlightCommand, FlightDecodeResult, FlightMotorDecoder
from .flight_adapter import (
    FLYBODY_CONTROL_TIMESTEP_SECONDS,
    FLYBODY_STEERING_COMMAND_DIM,
    FlyBodySteeringReference,
    LowLevelFlightCommand,
    MaleCNSFlightAdapter,
)
from .flight_registry import flight_population_ids, flight_population_types

__all__ = [
    "descending_ids",
    "forward_output_ids",
    "stop_output_ids",
    "turn_left_output_ids",
    "turn_right_output_ids",
    "walking_state_ids",
    "FlightCommand",
    "FlightDecodeResult",
    "FlightMotorDecoder",
    "LowLevelFlightCommand",
    "MaleCNSFlightAdapter",
    "FlyBodySteeringReference",
    "FLYBODY_STEERING_COMMAND_DIM",
    "FLYBODY_CONTROL_TIMESTEP_SECONDS",
    "flight_population_ids",
    "flight_population_types",
]
