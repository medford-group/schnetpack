import schnetpack.md.calculators.schnet_calculator
import schnetpack.md.initial_conditions as initcond
import schnetpack.md.calculators as calculators
import schnetpack.md.integrators as integrators

import schnetpack.md.simulation_hooks.thermostats as thermostats
import schnetpack.md.simulation_hooks.logging_hooks as logging_hooks
import schnetpack.md.simulation_hooks.sampling as sampling

from collections import OrderedDict


def model(x):
    """
    Dummy type for model class passed to CalculatorInit so basic conventions can be kept for other inputs

    Args:
        x (object): Torch model class
    Returns:
        object: The input model class
    """
    return x


class InitializerError(Exception):
    """
    Exception for SacredInit class.
    """

    pass


class Initializer:
    """
    Auxiliary class for setting up a molecular dynamics simulation with sacred in the run_dynamics.py script.
    Takes a dictionary of the form:
        init_dict = { 'type' : string identifying target class,
                      'name input1' : value,
                      'name_input2' : value,
                      ... }

    It first checks the predefined allowed_options for the class associated with the short string given in type. Then
    it uses the associated input_type (another string) to check for the expected input pattern in another predefined
    dictionary required_inputs. The values provided in name_input... are then checked for consistency with the expected
    input pattern and converted to the appropriate types. Afterwards, the class is initialized using these inputs and
    stored in the 'initialized' variable.

    allowed_options (dict) should have entries of the form:
        string identifying target class : {
            reference to class,
            string indicating input type for lookup in required_inputs,
            optional kwargs, which can be used to set up specific default settings
        }

    required_inputs (dict) should have entries of the form:
        string indicating input type : OrderedDict({
            name : type
        })
    An ordered dict has to be used to preserve the input order passed to the class.

    Additional entries in the input_dict not associated with a conventional input are piped directly into the class as
    **kwargs and can be used to access additional options. This should be used with caution, as no consistency checks
    are performed in this case.

    Args:
        init_dict (dict): Dictionary containing input specifications generated in run_dynamics.py
    """

    kind = "type"
    allowed_options = {"test": ("class_name", "input_type", "optional_kwargs")}
    required_inputs = {"input_type": OrderedDict({"name_1": str, "name_2": int})}

    def __init__(self, init_dict):

        self.initialized = None

        if not init_dict:
            self.initialized = None
        else:
            kind = init_dict[self.kind]

            if kind not in self.allowed_options:
                raise InitializerError(
                    "Unrecognized type {:s} for {:s}. Options are:\n  {:s}".format(
                        kind, self.__class__.__name__, ", ".join(self.allowed_options)
                    )
                )

            target_class, input_type, optional_inputs = self.allowed_options[kind]

            required_inputs = self.required_inputs[input_type]

            inputs = []
            for required in required_inputs:
                # Check if required inputs are specified
                if required not in init_dict:
                    raise InitializerError(
                        "Expected input {:s} for {:s}.".format(required, kind)
                    )
                else:
                    # Try to convert to requested type
                    try:
                        inputs.append(required_inputs[required](init_dict[required]))
                    except ValueError:
                        raise InitializerError(
                            "Expected type {:s} for argument {:s}".format(
                                required_inputs[required].__name__, required
                            )
                        )

            # Additional inputs
            extra_kwargs = {}
            for key in init_dict:
                if key not in required_inputs:
                    if key != self.kind:
                        extra_kwargs[key] = init_dict[key]

            if optional_inputs is not None:
                extra_kwargs.update(optional_inputs)

            self.initialized = target_class(*inputs, **extra_kwargs)


class ThermostatInit(Initializer):
    """
    Initialization instructions for thermostats. Optional instructions are used to define the massive and global
    Nose-Hoover chain thermostats. Two input cases exist, with all GLE based thermostats requiring an input file
    containing the thermostat matrices and all other types requiring specification of a time constant.
    """

    allowed_options = {
        "berendsen": (thermostats.BerendsenThermostat, "standard", None),
        "langevin": (thermostats.LangevinThermostat, "standard", None),
        "gle": (thermostats.GLEThermostat, "gle", None),
        "pile-l": (thermostats.PILELocalThermostat, "standard", None),
        "pile-g": (thermostats.PILEGlobalThermostat, "standard", None),
        "piglet": (thermostats.PIGLETThermostat, "gle", None),
        "nhc": (thermostats.NHCThermostat, "standard", None),
        "nhc-massive": (thermostats.NHCThermostat, "standard", {"massive": True}),
        "pi-nhc-l": (thermostats.NHCRingPolymerThermostat, "standard", None),
        "pi-nhc-g": (
            thermostats.NHCRingPolymerThermostat,
            "standard",
            {"local": False},
        ),
        "trpmd": (thermostats.TRPMDThermostat, "trpmd", None),
    }

    required_inputs = {
        "standard": OrderedDict({"temperature": float, "time_constant": float}),
        "gle": OrderedDict({"temperature": float, "gle_input": str}),
        "trpmd": OrderedDict({"temperature": float, "damping": float}),
    }


class IntegratorInit(Initializer):
    """
    Initialization instructions for the available integrators.
    """

    allowed_options = {
        "verlet": (integrators.VelocityVerlet, "verlet", None),
        "ring_polymer": (integrators.RingPolymer, "ring_polymer", None),
    }

    required_inputs = {
        "verlet": OrderedDict({"time_step": float}),
        "ring_polymer": OrderedDict(
            {"n_beads": int, "time_step": float, "temperature": float}
        ),
    }


class InitialConditionsInit(Initializer):
    """
    Initialization instructions for the available thermostats.
    """

    allowed_options = {"maxwell-boltzmann": (initcond.MaxwellBoltzmannInit, "mb", None)}
    required_inputs = {
        "mb": OrderedDict(
            {"temperature": float, "remove_translation": bool, "remove_rotation": bool}
        )
    }


class CalculatorInit(Initializer):
    """
    Initialization instructions for the available calculators.
    """

    allowed_options = {
        "schnet": (
            schnetpack.md.calculators.schnet_calculator.SchnetPackCalculator,
            "schnet",
            None,
        ),
        "orca": (calculators.OrcaCalculator, "orca", None),
        "sgdml": (calculators.OrcaCalculator, "sgdml", None),
    }
    required_inputs = {
        "schnet": OrderedDict(
            {"model": model, "required_properties": list, "force_handle": str}
        ),
        "orca": OrderedDict(
            {
                "required_properties": list,
                "force_handle": str,
                "compdir": str,
                "qm_executable": str,
                "orca_template": str,
            }
        ),
        "sgdml": OrderedDict({"model": model}),
    }


class BiasPotentialInit(Initializer):
    """
    Set up the available bias potentials
    """

    allowed_options = {
        "accelerated_md": (sampling.AcceleratedMD, "accelerated_md", None),
        "metadyn": (sampling.MetaDyn, "metadyn", None),
    }
    required_inputs = {
        "accelerated_md": OrderedDict(
            {"energy_threshold": float, "acceleration_factor": float}
        ),
        "metadyn": OrderedDict({"collective_variables": list}),
    }


class ColVars:
    available = {"bond": sampling.BondColvar}


class LoggerStreams:
    """
    Auxiliary class to provide short strings identifying the different available data streams for the FileLogger hook.
    """

    available = {
        "molecules": logging_hooks.MoleculeStream(),
        "properties": logging_hooks.PropertyStream(),
        "dynamic": logging_hooks.SimulationStream(),
    }


def get_data_streams(stream_list):
    """
    Auxiliary function to translate a list of identifier strings specified in LoggerStream.available into the
    corresponding DataStream classes to be used in the file logger.

    Args:
        stream_list: List of strings indicating the requested DataStreams for the file logger.

    Returns:
        list(object): List of DataStream objects.
    """
    streams = []
    for stream in stream_list:
        if stream not in LoggerStreams.available:
            raise ValueError("Stream {:s} not available for file logger".format(stream))
        streams.append(LoggerStreams.available[stream])

    return streams
