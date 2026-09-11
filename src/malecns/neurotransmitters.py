"""Names and handling policy for MaleCNS neurotransmitter predictions."""

NEUROTRANSMITTER_SOURCE = "body-neurotransmitters-male-cns-v1.0.feather"

# This is descriptive metadata only. It is not used to infer synaptic sign or
# to modify a future simulator's weights.
KNOWN_PREDICTION_FIELDS = (
    "predicted_neurotransmitter",
    "neurotransmitter_confidence",
)
