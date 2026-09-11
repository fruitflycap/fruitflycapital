from __future__ import annotations

import unittest

import pandas as pd

from malecns.neurotransmitters import KNOWN_PREDICTION_FIELDS
from malecns.neuprint_client import MaleCNSClient, _as_list
from malecns.annotations import incoming_edges, outgoing_edges, query_neurons
from malecns.loader import normalize_edges, normalize_neurons, read_feather
from malecns.schema import EDGE_COLUMNS, NEURON_COLUMNS
from malecns.validation import make_report
from malecns.brain import BrainSimulation
from malecns.motor.registry import (
    forward_output_ids,
    stop_output_ids,
    turn_left_output_ids,
    turn_right_output_ids,
    walking_state_ids,
)
from malecns.sensory.registry import visual_left_ids, visual_right_ids


class BootstrapWithoutOptionalDependenciesTest(unittest.TestCase):
    def test_canonical_columns_are_stable(self):
        self.assertEqual(EDGE_COLUMNS, ("source_body_id", "target_body_id", "synapse_weight"))
        self.assertIn("body_id", NEURON_COLUMNS)
        self.assertIn("predicted_neurotransmitter", NEURON_COLUMNS)

    def test_neurotransmitter_fields_are_descriptive(self):
        self.assertEqual(KNOWN_PREDICTION_FIELDS[0], "predicted_neurotransmitter")

    def test_as_list_handles_scalar_and_iterable(self):
        self.assertEqual(_as_list(12), [12])
        self.assertEqual(_as_list("DNge104"), ["DNge104"])
        self.assertEqual(_as_list([1, 2]), [1, 2])

    def test_client_rejects_non_malecns_dataset(self):
        with self.assertRaises(ValueError):
            MaleCNSClient(dataset="flywire:v783", client=object())

    def test_live_query_uses_malecns_side_property(self):
        class FakeClient:
            def fetch_custom(self, cypher, **kwargs):
                self.cypher = cypher
                return "fake-frame"

        fake = FakeClient()
        result = MaleCNSClient(client=fake).query_neurons(side="R")
        self.assertEqual(result, "fake-frame")
        self.assertIn("n.somaSide IN [\"R\"]", fake.cypher)


class FeatherNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.annotations = pd.DataFrame(
            {
                "bodyId": [101, 202, 303],
                "type": ["sensory_a", "DN_a", "MN_a"],
                "class": ["sensory", "descending", "motor"],
                "side": ["L", "R", "R"],
                "annotation_specific": ["kept", "kept", "kept"],
            }
        )
        self.nt = pd.DataFrame(
            {
                "bodyId": [101, 202, 303],
                "predicted_nt": ["acetylcholine", "glutamate", "GABA"],
                "nt_confidence": [0.9, 0.8, 0.7],
            }
        )
        self.stats = pd.DataFrame({"bodyId": [101, 202, 303], "pre": [4, 5, 6], "post": [7, 8, 9]})
        self.connectivity = pd.DataFrame(
            {"bodyId_pre": [101, 202, 303], "bodyId_post": [202, 303, 101], "weight": [2, 3, 4], "roi": ["A", "B", "C"]}
        )

    def test_feather_round_trip_and_join(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.feather"
            self.annotations.to_feather(path)
            loaded = read_feather(path)
            neurons = normalize_neurons(loaded, self.nt, self.stats)
        frame = neurons.dataframe
        self.assertEqual(frame["body_id"].tolist(), [101, 202, 303])
        self.assertEqual(frame["pre_count"].tolist(), [4, 5, 6])
        self.assertEqual(frame["predicted_neurotransmitter"].tolist(), ["acetylcholine", "glutamate", "GABA"])
        self.assertIn("annotation_specific", frame.columns)

    def test_edges_queries_and_report(self):
        neurons = normalize_neurons(self.annotations, self.nt, self.stats)
        edges = normalize_edges(self.connectivity)
        self.assertEqual(outgoing_edges(edges, 101)["target_body_id"].tolist(), [202])
        self.assertEqual(incoming_edges(edges, [101])["source_body_id"].tolist(), [303])
        self.assertEqual(query_neurons(neurons, class_name="descending")["body_id"].tolist(), [202])
        report = make_report(neurons, edges)
        self.assertEqual(report.loaded_neurons, 3)
        self.assertEqual(report.loaded_edges, 3)
        self.assertEqual(report.total_synaptic_weight, 9.0)
        self.assertEqual(report.sensory_neurons, 1)
        self.assertEqual(report.descending_neurons, 1)
        self.assertEqual(report.motor_neurons, 1)


class Brian2ReferenceSimulationTest(unittest.TestCase):
    def setUp(self):
        from malecns.loader import normalize_edges, normalize_neurons

        self.neurons = normalize_neurons(
            pd.DataFrame(
                {
                    "bodyId": [1, 2, 3],
                    "type": ["Stim", "Target", "GabaTarget"],
                    "class": ["sensory", "motor", "motor"],
                    "side": ["L", "R", "R"],
                    "predicted_nt": ["acetylcholine", "acetylcholine", "gaba"],
                }
            )
        )
        self.edges = normalize_edges(
            pd.DataFrame(
                {
                    "bodyId_pre": [1, 1],
                    "bodyId_post": [2, 3],
                    "weight": [100, 100],
                }
            )
        )

    def _run(self, frequency_hz=None, silence=False, seed=42):
        brain = BrainSimulation.from_tables(self.neurons, self.edges, seed=seed)
        if silence:
            brain.silence([1])
        if frequency_hz is not None:
            brain.stimulate([1], frequency_hz=frequency_hz)
        return brain.run(100.0)

    def test_no_stimulation_baseline_is_quiet(self):
        result = self._run()
        self.assertEqual(len(result.spikes), 0)

    def test_stimulation_propagates_to_downstream_neuron(self):
        result = self._run(frequency_hz=150.0)
        target_rate = result.firing_rates.loc[result.firing_rates["body_id"] == 2, "firing_rate_hz"].iloc[0]
        self.assertGreater(target_rate, 0.0)

    def test_silencing_source_removes_downstream_activity(self):
        result = self._run(frequency_hz=150.0, silence=True)
        target_spikes = result.firing_rates.loc[
            result.firing_rates["body_id"] == 2, "spike_count"
        ].iloc[0]
        # Shiu's silencing helper zeroes outgoing synapses; it does not
        # suppress externally driven spikes in the silenced source itself.
        self.assertEqual(target_spikes, 0)

    def test_identical_seed_is_reproducible(self):
        first = self._run(frequency_hz=150.0, seed=9)
        second = self._run(frequency_hz=150.0, seed=9)
        pd.testing.assert_frame_equal(first.spikes, second.spikes)
        pd.testing.assert_frame_equal(first.firing_rates, second.firing_rates)

    def test_changed_stimulation_changes_result(self):
        quiet = self._run(frequency_hz=0.0, seed=9)
        active = self._run(frequency_hz=150.0, seed=9)
        self.assertNotEqual(len(quiet.spikes), len(active.spikes))

    def test_streaming_external_rates_propagate_without_accumulating_inputs(self):
        brain = BrainSimulation.from_tables(self.neurons, self.edges, seed=42)
        brain.set_external_rates({1: 150.0})
        object_count = len(brain._network.objects)
        _, counts = brain.advance(100.0)
        self.assertGreater(counts.get(2, 0), 0)
        brain.set_external_rates({1: 0.0})
        self.assertEqual(len(brain._network.objects), object_count)

    def test_ambiguous_transmitter_is_excluded_by_default(self):
        from malecns.loader import normalize_neurons

        neurons = normalize_neurons(
            pd.DataFrame({"bodyId": [1, 2], "predicted_nt": ["glutamate", "gaba"]})
        )
        brain = BrainSimulation.from_tables(neurons, self.edges.dataframe.iloc[[0]], seed=1)
        self.assertEqual(len(brain.connectivity.included_edges), 0)
        self.assertEqual(len(brain.connectivity.excluded_edges), 1)

    def test_visual_histamine_uses_restricted_negative_sign(self):
        from malecns.brain.connectivity import ConnectivityMatrix
        neurons = normalize_neurons(
            pd.DataFrame(
                {
                    "bodyId": [1, 2],
                    "class": ["visual", "visual"],
                    "predicted_nt": ["histamine", "acetylcholine"],
                }
            )
        )
        edges = normalize_edges(pd.DataFrame({"bodyId_pre": [1], "bodyId_post": [2], "weight": [3]}))
        matrix = ConnectivityMatrix.from_tables(neurons, edges)
        self.assertEqual(len(matrix.included_edges), 1)
        self.assertEqual(matrix.included_edges.iloc[0]["sign"], -1.0)


class PopulationRegistryTest(unittest.TestCase):
    def setUp(self):
        self.neurons = normalize_neurons(
            pd.DataFrame(
                {
                    "bodyId": [1, 2, 3, 4, 5, 6, 7],
                    "class": ["visual", "visual", "olfactory", "mechanosensory", None, None, None],
                    "rootSide": ["L", "R", "L", "R", None, None, None],
                    "type": ["R8d", "R8d", "ORN_DA1", "JO-A2", "DNa01", "DNa02", "DNp09"],
                    "superclass": ["ol_sensory", "ol_sensory", "cb_sensory", "cb_sensory", "descending_neuron", "descending_neuron", "descending_neuron"],
                    "subclass": [None, None, None, "auditory", "xl", "xl", "xl"],
                    "side": [None, None, None, None, "L", "R", "L"],
                }
            )
        )

    def test_registry_uses_root_side_fallback(self):
        self.assertEqual(visual_left_ids(self.neurons, type_name="R8d"), [1])
        self.assertEqual(visual_right_ids(self.neurons, type_name="R8d"), [2])

    def test_motor_registry_is_exact_and_conservative(self):
        self.assertEqual(turn_left_output_ids(self.neurons), [5])
        self.assertEqual(turn_right_output_ids(self.neurons), [6])
        self.assertEqual(forward_output_ids(self.neurons), [7])
        self.assertEqual(stop_output_ids(self.neurons), [])
        self.assertEqual(walking_state_ids(self.neurons), [])


class SensoryEncodingTest(unittest.TestCase):
    def test_encoder_uses_documented_ids_and_leaves_unsupported_channels_empty(self):
        from malecns.brain.sensory_encoding import MaleCNSSensoryEncoder

        encoder = MaleCNSSensoryEncoder(
            [
                {"population": "visual_R8d", "bodyId": "11", "side_for_registry": "L"},
                {"population": "visual_R8d", "bodyId": "22", "side_for_registry": "R"},
                {"population": "olfactory_ORN_DA1", "bodyId": "33", "side_for_registry": "L"},
                {"population": "mechanosensory_auditory_JO-B1_b", "bodyId": "44", "side_for_registry": "L"},
            ]
        )
        encoded = encoder.encode(
            {
                "leftEye": {"meanLuminance": 1.0},
                "rightEye": {"meanLuminance": 0.0},
                "odor": {"concentration": 0.5},
                "contact": {"ground": True},
            }
        )
        self.assertEqual([entry["bodyId"] for entry in encoded["visual"]], [11, 22])
        self.assertEqual([entry["rateHz"] for entry in encoded["visual"]], [150.0, 0.0])
        self.assertEqual(encoded["olfactory"][0]["rateHz"], 75.0)
        self.assertEqual([entry["bodyId"] for entry in encoded["mechanosensory"]], [44])
        self.assertEqual(encoded["mechanosensory"][0]["rateHz"], 150.0)
        self.assertNotIn("contact_to_maleCNS_mechanosensory", encoded["unimplemented"])


class FlightDecoderTest(unittest.TestCase):
    def test_decoder_consumes_rates_and_returns_normalized_actuators(self):
        from malecns.motor.flight_decoder import FlightMotorDecoder

        decoder = FlightMotorDecoder(
            {
                "wing_amplitude": [10, 11],
                "saccade": [12],
                "saccade_left": [20],
                "saccade_right": [21],
                "turn_left_readout": [20],
                "turn_right_readout": [21],
            },
            reference_rate_hz=20.0,
        )
        result = decoder.decode({10: 40.0, 11: 20.0, 20: 0.0, 21: 20.0, 12: 4.0}, {12: 2})
        self.assertEqual(result.command.thrust, 1.0)
        self.assertEqual(result.command.yaw, 1.0)
        self.assertEqual(result.command.pitch, 0.0)
        self.assertEqual(result.command.roll, 0.0)
        self.assertEqual(result.spike_counts["12"], 2)
        self.assertGreater(result.low_level_command.forward_thrust, 0.0)
        self.assertIn("lowLevelFlightCommand", result.as_dict())
        self.assertEqual(result.as_dict()["steeringReference7d"]["dimension"], 7)

    def test_low_level_adapter_is_idle_without_neural_activity(self):
        from malecns.motor.flight_adapter import MaleCNSFlightAdapter

        command = MaleCNSFlightAdapter().adapt(
            thrust=0.0, yaw=0.0, pitch=0.0, roll=0.0, active_rate_hz=0.0
        )
        self.assertEqual(command.forward_thrust, 0.0)
        self.assertEqual(command.vertical_thrust, 0.5)
        self.assertEqual(command.steering_reference.dimension, 7)
        self.assertEqual(command.steering_reference.as_vector(), (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0))

    def test_flybody_steering_reference_maps_neural_readouts_only(self):
        from malecns.motor.flight_adapter import MaleCNSFlightAdapter

        command = MaleCNSFlightAdapter().adapt(
            thrust=1.0, yaw=-1.0, pitch=1.0, roll=-1.0, active_rate_hz=20.0
        )
        reference = command.steering_reference
        self.assertEqual(reference.ref_displacement_cm, (0.5, 0.0, 0.0))
        self.assertLess(reference.ref_root_quat_wxyz[3], 0.0)
        self.assertAlmostEqual(sum(value * value for value in reference.ref_root_quat_wxyz), 1.0)
        self.assertEqual(command.as_dict()["steeringReference7d"]["dimension"], 7)

    def test_flight_registry_uses_male_type_annotation(self):
        from malecns.loader import normalize_neurons
        from malecns.motor.flight_registry import flight_population_ids

        neurons = normalize_neurons(
            pd.DataFrame(
                {
                    "bodyId": [1, 2, 3, 4],
                    "type": ["DNg02_a", "DNp03", "DNp01", "not_a_dn"],
                    "mancType": ["DNg02", "DNp03", "DNp01", "DNg02"],
                    "superclass": ["descending_neuron"] * 4,
                    "somaSide": ["L", "R", "L", "R"],
                }
            )
        )
        populations = flight_population_ids(neurons)
        self.assertEqual(populations["wing_amplitude"], [1, 4])
        self.assertEqual(populations["saccade"], [2])
        self.assertEqual(populations["escape_takeoff"], [3])


if __name__ == "__main__":
    unittest.main()
