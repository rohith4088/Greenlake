# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from copy import deepcopy
import os
import yaml
import json


def __setattrs__(self, config_attrs):
    """Dynamically set attributes of an object based on the provided dictionary.

    Args:
        config_attrs (dict): Dictionary whose keys will be added as attributes
            to the object with corresponding values.

    Returns:
        (dict): Dictionary of attribute names and their values.
    """
    attr_data_dict = dict()
    for key, value in config_attrs.items():
        if hasattr(self, key):
            attr_data_dict[key] = getattr(self, key)
        else:
            attr_data_dict[key] = value

    return attr_data_dict


def create_attrs(obj, data_dictionary):
    """Create class attributes from a dictionary.

    Uses setattr() to set the value of attributes on the specified object.
    If an attribute already exists and its current value is not None,
    it keeps the previous value.

    Args:
        obj (object): Object instance to create/set attributes on.
        data_dictionary (dict): Dictionary containing keys that will become attributes.
    """
    # Used to create a deep copy of the dictionary
    dictionary_var = deepcopy(data_dictionary)

    # K is the argument and V is the value of the given argument
    for k, v in dictionary_var.items():
        # In case a key has '-' inside it's name.
        k = k.replace("-", "_")

        obj.__dict__[k] = v


def parse_input_file(file_path):
    """Parse data from a YAML or JSON file.

    Args:
        file_path (str): Path to the file.

    Returns:
        (dict): Parsed data from the file.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If the file format is unsupported or file cannot be loaded.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        with open(file_path, "r") as file:
            if file_path.endswith(".yaml") or file_path.endswith(".yml"):
                return yaml.safe_load(file)
            elif file_path.endswith(".json"):
                return json.load(file)
            else:
                raise ValueError("Unsupported file format. Use YAML or JSON.")
    except Exception as e:
        raise ValueError(f"Failed to parse data from file: {e}")
