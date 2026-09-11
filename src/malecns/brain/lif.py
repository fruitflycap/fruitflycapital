"""Brian2 implementation of the published Shiu et al. LIF equations."""

from __future__ import annotations

from textwrap import dedent

from .parameters import LIFParameters


def build_neuron_group(n_neurons: int, parameters: LIFParameters):
    """Construct and initialize the Brian2 neuron group."""
    try:
        from brian2 import NeuronGroup, mV, ms
    except ImportError as exc:  # pragma: no cover - dependency environment
        raise ImportError("Install Brian2 to run the neural dynamics") from exc
    namespace = {
        "v_0": parameters.v_0_mV * mV,
        "v_rst": parameters.v_reset_mV * mV,
        "v_th": parameters.v_threshold_mV * mV,
        "t_mbr": parameters.membrane_time_ms * ms,
        "tau": parameters.synaptic_time_ms * ms,
    }
    equations = dedent(
        """
        dv/dt = (v_0 - v + g) / t_mbr : volt (unless refractory)
        dg/dt = -g / tau               : volt (unless refractory)
        rfc                            : second
        """
    )
    group = NeuronGroup(
        N=n_neurons,
        model=equations,
        method="linear",
        threshold="v > v_th",
        reset="v = v_rst; g = 0 * mV",
        refractory="rfc",
        namespace=namespace,
        name="malecns_neurons",
    )
    group.v = namespace["v_0"]
    group.g = 0 * mV
    group.rfc = parameters.refractory_ms * ms
    return group
