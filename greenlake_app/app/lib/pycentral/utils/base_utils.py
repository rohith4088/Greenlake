# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

import logging
import yaml
import json
import os
from urllib.parse import urlencode, urlparse, urlunparse
from .constants import CLUSTER_BASE_URLS, GLP_URLS
from .common_utils import parse_input_file

try:
    import colorlog  # type: ignore

    COLOR = True
except (ImportError, ModuleNotFoundError):
    COLOR = False
C_LOG_LEVEL = {
    "CRITICAL": 50,
    "ERROR": 40,
    "WARNING": 30,
    "INFO": 20,
    "DEBUG": 10,
    "NOTSET": 0,
}

SUPPORTED_APPS = ["new_central", "glp"]
NEW_CENTRAL_C_DEFAULT_ARGS = {
    "base_url": None,
    "client_id": None,
    "client_secret": None,
    "access_token": None,
}
URL_BASE_ERR_MESSAGE = "Please provide the base_url of API Gateway where Central account is provisioned!"


def new_parse_input_args(token_info):
    """Parse and validate the input token information.

    Args:
        token_info (dict or str): Dictionary containing token information or a file path
            to a YAML/JSON file with token information.

    Returns:
        (dict): Parsed token information for supported applications.

    Raises:
        ValueError: If the token_info is invalid.
    """
    token_info = load_token_info(token_info)

    apps_token_info = {}

    for app, app_token_info in token_info.items():
        if app not in SUPPORTED_APPS:
            raise ValueError(
                f"Unknown app name '{app}' provided. Supported apps: {', '.join(SUPPORTED_APPS)}"
            )

        # Resolve base_url using cluster_name or validate provided base_url
        app_token_info["base_url"] = _resolve_base_url(app, app_token_info)

        # Validate required keys for token creation
        _validate_token_creation_keys(app_token_info)

        # Merge with default arguments
        default_args = {**NEW_CENTRAL_C_DEFAULT_ARGS, **app_token_info}
        apps_token_info[app] = default_args

    if not apps_token_info:
        raise ValueError(
            f"No valid token information provided. Supported apps: {', '.join(SUPPORTED_APPS)}"
        )

    return apps_token_info


def load_token_info(token_info):
    """Load token information from a file if it's a string path, or return the dictionary as is.

    Args:
        token_info (dict or str): Either a dictionary containing token information or a
            string path to a YAML/JSON file with token information.

    Returns:
        (dict): Parsed token information dictionary.

    Raises:
        ValueError: If the file format is unsupported or the file cannot be parsed.
        FileNotFoundError: If the specified file path does not exist.
    """
    if isinstance(token_info, str):
        try:
            token_info = parse_input_file(token_info)
        except (ValueError, FileNotFoundError) as e:
            # Re-raise the exception with additional context
            raise type(e)(f"Failed to load token information: {str(e)}")
    return token_info


def _resolve_base_url(app, app_token_info):
    """Resolve the base_url using cluster_name or validate the provided base_url.

    Args:
        app (str): Name of the application (e.g., "new_central", "glp").
        app_token_info (dict): Token information for a specific app.

    Returns:
        (str): Validated or resolved base_url.

    Raises:
        ValueError: If both cluster_name and base_url are provided or neither is valid.
    """
    if app == "new_central":
        if "cluster_name" in app_token_info and "base_url" in app_token_info:
            raise ValueError(
                "You cannot provide both 'cluster_name' and 'base_url' for new_central. Please provide only one."
            )
        if "cluster_name" in app_token_info:
            cluster_name = app_token_info["cluster_name"]
            if cluster_name in CLUSTER_BASE_URLS:
                return CLUSTER_BASE_URLS[cluster_name]
            else:
                raise ValueError(
                    f"Invalid cluster_name '{cluster_name}' provided. Supported clusters: {', '.join(CLUSTER_BASE_URLS.keys())}"
                )
        if "base_url" in app_token_info:
            return valid_url(app_token_info["base_url"])
        raise ValueError(
            "For new_central, either 'cluster_name' or 'base_url' must be provided."
        )
    elif app == "glp":
        if "base_url" not in app_token_info:
            app_token_info["base_url"] = GLP_URLS["BaseURL"]
        return valid_url(app_token_info["base_url"])
    else:
        raise ValueError(f"Unsupported app '{app}'.")


def _validate_token_creation_keys(app_token_info):
    """Validate that the required keys for token creation are present.

    Args:
        app_token_info (dict): Token information for a specific app.

    Raises:
        ValueError: If required keys are missing.

    Note:
        Internal SDK function
    """
    if "access_token" not in app_token_info:
        required_keys = {"client_id", "client_secret"}
        missing_keys = required_keys - app_token_info.keys()
        if missing_keys:
            raise ValueError(
                f"Missing required keys for token creation: {', '.join(missing_keys)}. "
                "Provide either a valid access token or the required credentials (client_id, client_secret) needed to generate an access token."
            )


def build_url(base_url, path="", params="", query={}, fragment=""):
    """Construct a complete URL based on multiple parts of the URL.

    Args:
        base_url (str): Base URL for an HTTP request.
        path (str, optional): API endpoint path.
        params (str, optional): API endpoint path parameters.
        query (dict, optional): HTTP request URL query parameters.
        fragment (str, optional): URL fragment identifier.

    Returns:
        (str): Parsed URL.
    """
    base_url = valid_url(base_url)
    parsed_baseurl = urlparse(base_url)
    scheme = parsed_baseurl.scheme
    netloc = parsed_baseurl.netloc
    query = urlencode(query)
    url = urlunparse((scheme, netloc, path, params, query, fragment))
    return url


def console_logger(name, level="DEBUG"):
    """Create an instance of python logging with a formatted output.

    Sets the following format for log messages: `<date> <time> - <name> - <level> - <message>`

    Args:
        name (str): String displayed after date and time. Define it to identify
            from which part of the code the log message is generated.
        level (str, optional): Logging level to display messages from a certain level.

    Returns:
        (logging.Logger): An instance of the logging.Logger class.
    """
    channel_handler = logging.StreamHandler()
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    f = format
    if COLOR:
        cformat = "%(log_color)s" + format
        f = colorlog.ColoredFormatter(
            cformat,
            date_format,
            log_colors={
                "DEBUG": "bold_cyan",
                "INFO": "blue",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    else:
        f = logging.Formatter(format, date_format)
    channel_handler.setFormatter(f)

    logger = logging.getLogger(name)
    logger.setLevel(C_LOG_LEVEL[level])

    # Only add Handler if not already present
    if not logger.handlers:
        logger.addHandler(channel_handler)

    return logger


def valid_url(url):
    """Verify and return the URL in a valid format.

    If the URL is missing the https prefix, the function will prepend the prefix
    after verifying that it's a valid base URL of an HPE Aruba Networking Central cluster.

    Args:
        url (str): Base URL for an HTTP request.

    Returns:
        (str): Valid base URL.

    Raises:
        ValueError: If the URL is invalid.
    """
    parsed_url = urlparse(url)
    if all([parsed_url.scheme, parsed_url.netloc]):
        return parsed_url.geturl()
    elif bool(parsed_url.scheme) is False and bool(parsed_url.path):
        parsed_url = parsed_url._replace(
            **{"scheme": "https", "netloc": parsed_url.path, "path": ""}
        )
        return parsed_url.geturl()
    else:
        errorMessage = (
            "Invalid Base URL - " + f"{url}\n" + URL_BASE_ERR_MESSAGE
        )
        raise ValueError(errorMessage)


def save_access_token(app_name, access_token, token_file_path, logger):
    """Update the access token for a specific application in the credentials file.

    Args:
        app_name (str): Name of the application to update (e.g., "new_central", "glp").
        access_token (str): The new access token value.
        token_file_path (str): Path to the credentials file.
        logger (logging.Logger): Logger instance to log messages.

    Raises:
        FileNotFoundError: If the credentials file doesn't exist.
        ValueError: If the app_name isn't found in the credentials file.
        IOError: If there is an error writing to the credentials file.
    """
    if not os.path.isfile(token_file_path):
        raise FileNotFoundError(
            f"Credentials file not found: {token_file_path}"
        )

    # Load credentials file using existing helper function
    file_data = parse_input_file(token_file_path)
    is_json = token_file_path.endswith(".json")

    # Update the access token for the specified app
    if app_name not in file_data:
        raise ValueError(f"App '{app_name}' not found in credentials file")

    file_data[app_name]["access_token"] = access_token

    # Write updated data back to file
    try:
        with open(token_file_path, "w") as f:
            if is_json:
                json.dump(file_data, f, indent=4, sort_keys=False)
            else:
                yaml.dump(file_data, f, sort_keys=False)
            logger.info(
                f"Successfully saved {app_name}'s access token in {token_file_path}"
            )
    except Exception as e:
        raise IOError(f"Failed to write updated credentials to file: {e}")
