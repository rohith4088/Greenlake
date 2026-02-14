# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License


from pycentral.exceptions import ParameterError


def validate_local(local):
    """Validate local profile attributes and prepare them for API requests.

    Args:
        local (dict or None): Local profile attributes dictionary containing
            scope_id (int) and persona (str).

    Returns:
        (dict): Validated local attributes dictionary with object_type set to "LOCAL".

    Raises:
        ParameterError: If local is not a dictionary or missing required keys
            with correct types.
    """
    required_keys = {"scope_id": int, "persona": str}
    local_attributes = dict()
    if local:
        if not isinstance(local, dict):
            raise ParameterError(
                "Invalid local profile attributes. Please provide a valid dictionary."
            )
        for key, expected_type in required_keys.items():
            if key not in local or not isinstance(local[key], expected_type):
                raise ParameterError(
                    f"Invalid local profile attributes. Key '{key}' must be of type {expected_type.__name__}."
                )
        local_attributes = {"object_type": "LOCAL"}
        local_attributes.update(local)
    return local_attributes
