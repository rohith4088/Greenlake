# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from oauthlib.oauth2.rfc6749.errors import InvalidClientError
from requests_oauthlib import OAuth2Session
from requests.auth import HTTPBasicAuth
from oauthlib.oauth2 import BackendApplicationClient
import json
import requests
from .utils.base_utils import (
    build_url,
    new_parse_input_args,
    console_logger,
    save_access_token,
)
from .scopes import Scopes
from .utils import AUTHENTICATION
from .exceptions import LoginError, ResponseError

SUPPORTED_API_METHODS = ("POST", "PATCH", "DELETE", "GET", "PUT")


class NewCentralBase:
    def __init__(
        self, token_info, logger=None, log_level="DEBUG", enable_scope=False
    ):
        """Constructor initializes the NewCentralBase class with token information and logging configuration.

        Validates and processes the provided token information, sets up logging,
        and optionally initializes scope-related functionality.

        Args:
            token_info (dict or str): Dictionary containing token information for supported
                applications (new_central, glp). Can also be a string path to a YAML or
                JSON file with token information.
            logger (logging.Logger, optional): Logger instance. Defaults to None.
            log_level (str, optional): Logging level. Defaults to "DEBUG".
            enable_scope (bool, optional): Flag to enable scope management. If True, the SDK
                will automatically fetch data about existing scopes and associated profiles,
                simplifying scope and configuration management. If False, scope-related API
                calls are disabled, resulting in faster initialization. Defaults to False.
        """
        self.token_info = new_parse_input_args(token_info)
        self.token_file_path = None
        if isinstance(token_info, str):
            self.token_file_path = token_info
        self.logger = self.set_logger(log_level, logger)
        self.scopes = None
        for app in self.token_info:
            app_token_info = self.token_info[app]
            if (
                "access_token" not in app_token_info
                or app_token_info["access_token"] is None
            ):
                self.create_token(app)
        if enable_scope:
            self.scopes = Scopes(central_conn=self)

    def set_logger(self, log_level, logger=None):
        """Set up the logger.

        Args:
            log_level (str): Logging level.
            logger (logging.Logger, optional): Logger instance. Defaults to None.

        Returns:
            (logging.Logger): Logger instance.
        """
        if logger:
            return logger
        else:
            return console_logger("NEW CENTRAL BASE", log_level)

    def create_token(self, app_name):
        """Create a new access token for the specified application.

        Generates a new access token using the client credentials for the specified
        application, updates the `self.token_info` dictionary with the new token,
        and optionally saves it to a file.

        Args:
            app_name (str): Name of the application. Supported applications: "new_central", "glp".

        Returns:
            (str): Access token.

        Raises:
            LoginError: If there is an error during token creation.
        """
        client_id, client_secret = self._return_client_credentials(app_name)
        client = BackendApplicationClient(client_id)

        oauth = OAuth2Session(client=client)
        auth = HTTPBasicAuth(client_id, client_secret)

        try:
            self.logger.info(f"Attempting to create new token from {app_name}")
            token = oauth.fetch_token(
                token_url=AUTHENTICATION["OAUTH"], auth=auth
            )

            if "access_token" in token:
                self.logger.info(
                    f"{app_name} Login Successful.. Obtained Access Token!"
                )
                self.token_info[app_name]["access_token"] = token[
                    "access_token"
                ]
                if self.token_file_path:
                    save_access_token(
                        app_name,
                        token["access_token"],
                        self.token_file_path,
                        self.logger,
                    )
                return token["access_token"]
        except Exception as e:
            # unified extraction of status code (from exception or its response)
            status_code = getattr(e, "status_code", None)
            resp = getattr(e, "response", None)
            if resp is not None:
                status_code = getattr(resp, "status_code", status_code)

            # special-case invalid client credentials to provide a clearer, actionable message
            if isinstance(e, InvalidClientError):
                description = getattr(e, "description", None) or str(e)
                msg = (
                    f"{description} for {app_name}. "
                    "Provide valid client_id and client_secret to create an access token."
                )
            else:
                msg = str(e) or "Unexpected error while creating access token"

            self.logger.error(msg)
            raise LoginError(msg, status_code)

    def handle_expired_token(self, app_name):
        """Handle expired access token by creating a new one.

        Args:
            app_name (str): Name of the application.

        Raises:
            LoginError: If client credentials are missing.
        """
        self.logger.info(
            f"{app_name} access token has expired. Handling Token Expiry..."
        )
        client_id, client_secret = self._return_client_credentials(app_name)
        if any(
            credential is None for credential in [client_id, client_secret]
        ):
            msg = f"Please provide client_id and client_secret in {app_name} required to generate an access token"
            self.logger.error(msg)
            raise LoginError(msg)
        else:
            self.create_token(app_name)

    def command(
        self,
        api_method,
        api_path,
        app_name="new_central",
        api_data={},
        api_params={},
        headers={},
        files={},
    ):
        """Execute an API command to HPE Aruba Networking Central or GreenLake Platform.

        This is the primary method for making API calls from the SDK. It handles
        authentication, token refresh on expiry, request formatting, and response
        parsing. All other SDK modules internally use this method to make API calls.

        The method automatically:
            - Validates the application name and HTTP method
            - Constructs the full URL from self.base_url and api_path
            - Adds appropriate headers (Content-Type, Accept) if not provided
            - Serializes api_data to JSON when Content-Type is application/json
            - Handles 401 errors by refreshing the access token and retrying if client credentials are available
            - Parses JSON responses when possible

        Args:
            api_method (str): HTTP method for the API call. Supported methods:
                POST, PATCH, DELETE, GET, PUT.
            api_path (str): API endpoint path (e.g., "monitoring/v1/aps").
                This is appended to the base_url configured in token_info.
            app_name (str, optional): Target application for the API call.
                Use "new_central" for HPE Aruba Networking Central APIs (default).
                Use "glp" for GreenLake Platform APIs.
            api_data (dict, optional): Request body/payload to be sent. Automatically
                serialized to JSON if Content-Type is application/json. Defaults to {}.
            api_params (dict, optional): URL query parameters for the API request.
                Defaults to {}.
            headers (dict, optional): Custom HTTP headers. If not provided and no files
                are being uploaded, defaults to {"Content-Type": "application/json",
                "Accept": "application/json"}.
            files (dict, optional): Files to upload in multipart/form-data requests.
                When provided, Content-Type header is not automatically set. Defaults to {}.

        Returns:
            (dict): API response containing:
                - code (int): HTTP status code
                - msg (dict or str): Parsed JSON response body, or raw text if not JSON
                - headers (dict): Response headers

        Raises:
            ResponseError: If there is an error during the API call.
        """
        self._validate_request(app_name, api_method)

        retry = 0
        result = ""

        limit_reached = False
        try:
            while not limit_reached:
                url = build_url(
                    self.token_info[app_name]["base_url"], api_path
                )

                if not headers and not files:
                    headers = {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    }
                if api_data and headers["Content-Type"] == "application/json":
                    api_data = json.dumps(api_data)

                resp = self.request_url(
                    url=url,
                    data=api_data,
                    method=api_method,
                    headers=headers,
                    params=api_params,
                    files=files,
                    access_token=self.token_info[app_name]["access_token"],
                )
                if resp.status_code == 401:
                    if retry >= 1:
                        self.logger.error(
                            "Received error 401 on requesting url "
                            "%s with resp %s" % (str(url), str(resp.text))
                        )
                        limit_reached = True
                        break
                    self.handle_expired_token(app_name)
                    retry += 1
                else:
                    break

            result = {
                "code": resp.status_code,
                "msg": resp.text,
                "headers": dict(resp.headers),
            }

            try:
                result["msg"] = json.loads(result["msg"])
            except BaseException:
                result["msg"] = str(resp.text)

            return result

        except Exception as err:
            err_str = f"{api_method} FAILURE "
            self.logger.error(err)
            raise ResponseError(err_str, err)

    def request_url(
        self,
        url,
        access_token,
        data={},
        method="GET",
        headers={},
        params={},
        files={},
    ):
        """Make an API call to application (New Central or GLP) via the requests library.

        Args:
            url (str): HTTP Request URL string.
            access_token (str): Access token for authentication.
            data (dict, optional): HTTP Request payload. Defaults to {}.
            method (str, optional): HTTP Request Method supported by GLP/New Central.
                Defaults to "GET".
            headers (dict, optional): HTTP Request headers. Defaults to {}.
            params (dict, optional): HTTP URL query parameters. Defaults to {}.
            files (dict, optional): Files dictionary with file pointer depending on
                API endpoint as accepted by GLP/New Central. Defaults to {}.

        Returns:
            (requests.models.Response): HTTP response of API call using requests library.

        Raises:
            ResponseError: If there is an error during the API call.
        """
        resp = None

        auth = BearerAuth(access_token)
        s = requests.Session()
        req = requests.Request(
            method=method,
            url=url,
            headers=headers,
            files=files,
            auth=auth,
            params=params,
            data=data,
            cookies=self.token_info.get("glp", {}).get("cookies", {}) 
        )
        prepped = s.prepare_request(req)
        settings = s.merge_environment_settings(
            prepped.url, {}, None, True, None
        )
        try:
            resp = s.send(prepped, **settings)
            return resp
        except Exception as err:
            str1 = "Failed making request to URL %s " % url
            str2 = "with error %s" % str(err)
            err_str = f"{str1} {str2}"
            self.logger.error(str1 + str2)
            raise ResponseError(err_str, err)

    def _validate_request(self, app_name, method):
        """Validate that provided app has access_token and a valid HTTP method.

        Args:
            app_name (str): Name of the application.
            method (str): HTTP method to be validated.

        Raises:
            ValueError: If app_name is not in token_info or access_token is missing.
            ValueError: If the method is not supported.
        """
        if app_name not in self.token_info:
            error_string = (
                f"Missing access_token for {app_name}. Please provide access token "
                f"or client credentials to generate an access token for app - {app_name}"
            )
            self.logger.error(error_string)
            raise ValueError(error_string)

        if method not in SUPPORTED_API_METHODS:
            error_string = (
                f"HTTP method '{method}' not supported. Please provide an API with one of the "
                f"supported methods - {', '.join(SUPPORTED_API_METHODS)}"
            )
            self.logger.error(error_string)
            raise ValueError(error_string)

    def _return_client_credentials(self, app_name):
        """Return client credentials for the specified application.

        Args:
            app_name (str): Name of the application.

        Returns:
            (tuple): Client ID and client secret as a tuple (client_id, client_secret).
        """
        app_token_info = self.token_info[app_name]
        if all(
            client_key in app_token_info
            for client_key in ("client_id", "client_secret")
        ):
            client_id = app_token_info["client_id"]
            client_secret = app_token_info["client_secret"]
            return client_id, client_secret

    def get_scopes(self):
        """Set up the scopes for the current instance by creating a Scopes object.

        Initializes the `scopes` attribute using the `Scopes` class, passing the
        current instance as the `central_conn` parameter. If the `scopes` attribute
        is already initialized, it simply returns the existing object.

        Returns:
            (Scopes): The initialized or existing Scopes object.
        """
        if self.scopes is None:
            self.scopes = Scopes(central_conn=self)
        return self.scopes


class BearerAuth(requests.auth.AuthBase):
    """Uses Bearer Auth method to generate the authorization header from New Central or GLP Access Token.

    Args:
        token (str): New Central or GLP Access Token.
    """

    def __init__(self, token):
        """Constructor Method.

        Args:
            token (str): New Central or GLP Access Token.
        """
        self.token = token

    def __call__(self, r):
        """Internal method returning auth.

        Args:
            r (requests.models.PreparedRequest): Request object.

        Returns:
            (requests.models.PreparedRequest): Modified request object with authorization header.
        """
        r.headers["authorization"] = "Bearer " + self.token
        return r
