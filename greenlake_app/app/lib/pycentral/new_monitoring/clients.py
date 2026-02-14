from ..utils.monitoring_utils import (
    execute_get,
    build_timestamp_filter,
)
from ..exceptions import ParameterError

CLIENT_LIMIT = 100


class Clients:
    @staticmethod
    def get_all_site_clients(
        central_conn,
        site_id,
        serial_number=None,
        filter_str=None,
        sort=None,
        duration=None,
        start_time=None,
        end_time=None,
    ):
        """
        Return all clients for a site, handling pagination.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            serial_number (str, optional): Device serial number to filter clients.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).
            duration (int, optional): Duration in seconds for a relative time window.
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).

        Returns:
            (list): All client details for the specified site.
        """
        Clients._validate_site_id(site_id)
        clients = []
        total_clients = None
        next_page = 1
        while True:
            resp = Clients.get_site_clients(
                central_conn=central_conn,
                site_id=site_id,
                serial_number=serial_number,
                filter_str=filter_str,
                sort=sort,
                next_page=next_page,
                limit=CLIENT_LIMIT,
                duration=duration,
                start_time=start_time,
                end_time=end_time,
            )
            if total_clients is None:
                total_clients = resp.get("total", 0)
            clients.extend(resp.get("items", []))
            if len(clients) == total_clients:
                break
            next_val = resp.get("next")
            if not next_val:
                break
            next_page = int(next_val)
        return clients

    @staticmethod
    def get_wireless_clients(
        central_conn,
        site_id,
        sort=None,
        duration=None,
        start_time=None,
        end_time=None,
    ):
        """
        Fetch wireless clients for a site.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            sort (str, optional): Optional sort expression.
            duration (int, optional): Duration in seconds for a relative time window.
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).

        Returns:
            (list): List of wireless client for the specified site.

        Raises:
            ParameterError: If site_id is not provided or invalid.
        """
        return Clients.get_all_site_clients(
            central_conn=central_conn,
            site_id=site_id,
            filter_str="type eq Wireless",
            sort=sort,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    def get_wired_clients(
        central_conn,
        site_id,
        sort=None,
        duration=None,
        start_time=None,
        end_time=None,
    ):
        """
        Fetch wired clients for a site.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            sort (str, optional): Optional sort expression.
            duration (int, optional): Duration in seconds for a relative time window.
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).

        Returns:
            (list): List of wired client for the specified site.

        Raises:
            ParameterError: If site_id is not provided or invalid.
        """
        return Clients.get_all_site_clients(
            central_conn=central_conn,
            site_id=site_id,
            filter_str="type eq Wired",
            sort=sort,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    def get_clients_associated_device(
        central_conn,
        site_id,
        serial_number,
    ):
        """
        Fetch clients associated with a specific device in a site.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            serial_number (str): Device serial number to filter clients.

        Returns:
            (list): Clients associated with the specified device.

        Raises:
            ParameterError: If site_id or serial_number is missing/invalid.
        """
        return Clients.get_all_site_clients(
            central_conn=central_conn,
            site_id=site_id,
            serial_number=serial_number,
        )

    @staticmethod
    def get_connected_clients(
        central_conn,
        site_id,
    ):
        """
        Fetch connected clients for a site.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.

        Returns:
            (list[dict]): Connected clients for the site.

        Raises:
            ParameterError: If site_id is missing/invalid.
        """
        return Clients.get_all_site_clients(
            central_conn=central_conn,
            site_id=site_id,
            filter_str="status eq Connected",
        )

    @staticmethod
    def get_disconnected_clients(
        central_conn,
        site_id,
    ):
        """
        Fetch disconnected clients for a site.

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.

        Returns:
            (list[dict]): Disconnected clients for the site.

        Raises:
            ParameterError: If site_id is missing/invalid.
        """
        return Clients.get_all_site_clients(
            central_conn=central_conn,
            site_id=site_id,
            filter_str="status in (Disconnected, Failed)",
        )

    @staticmethod
    def get_site_clients(
        central_conn,
        site_id,
        serial_number=None,
        filter_str=None,
        sort=None,
        next_page=1,
        limit=CLIENT_LIMIT,
        duration=None,
        start_time=None,
        end_time=None,
    ):
        """
        Fetch clients for a site.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/clients`

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            serial_number (str, optional): Device serial number to filter clients.
            filter_str (str, optional): Optional filter expression (supported fields documented in API Reference Guide).
            sort (str, optional): Optional sort parameter (supported fields documented in API Reference Guide).
            next_page (int, optional): Page token/index for pagination.
            limit (int, optional): Maximum number of items to return.
            duration (int, optional): Duration (seconds) for relative time window.
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).

        Returns:
            (dict): Raw API response containing keys like 'items', 'total', and 'next'.

        Raises:
            ParameterError: If site_id is missing/invalid.
        """
        path = "clients"

        Clients._validate_site_id(site_id)
        params = {
            "site-id": site_id,
            "serial-number": serial_number,
            "filter": filter_str,
            "sort": sort,
            "next": next_page,
            "limit": limit,
        }
        if start_time is None and end_time is None and duration is None:
            return execute_get(central_conn, endpoint=path, params=params)

        params = Clients._time_filter(
            params=params,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
        )

        return execute_get(central_conn, endpoint=path, params=params)

    @staticmethod
    def get_client_trends(
        central_conn,
        site_id,
        group_by=None,
        client_type=None,
        serial_number=None,
        start_time=None,
        end_time=None,
        duration=None,
        return_raw_response=False,
    ):
        """
        Fetch client trend data for a site.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/clients/trends`

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            group_by (str, optional): Dimension to group results by (e.g., 'mac', 'ap').
            client_type (str, optional): Trend type (passed as 'type' in the request).
            serial_number (str, optional): Device serial number to filter the trend data.
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).
            duration (int, optional): Duration (seconds) for relative time window.
            return_raw_response (bool, optional): If True, return the raw API payload.

        Returns:
            (list[dict] or dict): Processed list of timestamped samples, or raw response if requested.

        Raises:
            ParameterError: If site_id is missing/invalid.
        """
        path = "clients/trends"

        Clients._validate_site_id(site_id)
        params = {
            "site-id": site_id,
            "group-by": group_by,
            "type": client_type,
            "serial-number": serial_number,
        }

        if start_time is None and end_time is None and duration is None:
            response = execute_get(central_conn, endpoint=path, params=params)
        else:
            params = Clients._time_filter(
                params=params,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
            )

            response = execute_get(central_conn, endpoint=path, params=params)
        if return_raw_response:
            return response

        return Clients._process_client_trend_samples(response)

    @staticmethod
    def get_top_n_site_clients(
        central_conn,
        site_id,
        serial_number=None,
        count=None,
        start_time=None,
        end_time=None,
        duration=None,
    ):
        """
        Fetch the top-N clients by usage for a site.

        This method makes an API call to the following endpoint - `GET network-monitoring/v1alpha1/clients/usage/topn`

        Args:
            central_conn (NewCentralBase): Central connection object.
            site_id (str|int): Identifier of the site to query.
            serial_number (str, optional): Device serial number to scope the query.
            count (int, optional): Number of top clients to return (1..100).
            start_time (int, optional): Start time (epoch seconds).
            end_time (int, optional): End time (epoch seconds).
            duration (int, optional): Duration (seconds) for relative time window.

        Returns:
            (dict): Raw API response containing top-N usage data.

        Raises:
            ParameterError: If site_id is missing/invalid or if count is provided but not in the range 1..100.
        """
        path = "clients/usage/topn"
        Clients._validate_site_id(site_id)

        if count is not None and (count > 100 or count < 1):
            raise ParameterError("Count must be between 1 and 100")

        params = {
            "site-id": site_id,
            "serial-number": serial_number,
            "count": count,
        }

        if start_time is None and end_time is None and duration is None:
            return execute_get(central_conn, endpoint=path, params=params)

        params = Clients._time_filter(
            params=params,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
        )

        return execute_get(central_conn, endpoint=path, params=params)

    def _time_filter(params, start_time, end_time, duration):
        """
        Apply a time filter to params using unix timestamps.

        Args:
            params (dict): Existing query params to augment.
            start_time (int|None): Start time (epoch seconds).
            end_time (int|None): End time (epoch seconds).
            duration (int|None): Duration in seconds.

        Returns:
            (dict): Params augmented with 'start-query-time' and 'end-query-time'.

        Note:
            Internal SDK function
        """
        start_unix, end_unix = build_timestamp_filter(
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            fmt="unix",
        )
        params["start-query-time"] = start_unix
        params["end-query-time"] = end_unix
        return params

    def _process_client_trend_samples(payload):
        """
        Normalize client trend payload into a list of timestamped dicts.

        Args:
            payload (dict): Raw trend payload with 'categories' and 'samples'.

        Returns:
            (list[dict]): Normalized rows with 'timestamp' and category/value pairs.

        Note:
            Internal SDK function
        """
        categories = payload.get("categories", [])
        samples = payload.get("samples", [])
        out = []
        for s in samples:
            row = {"timestamp": s.get("ts") or s.get("timestamp")}
            vals = s.get("data")
            if isinstance(vals, (list, tuple)):
                for cat, val in zip(categories, vals):
                    row[cat] = val
            else:
                if categories:
                    row[categories[0]] = vals
                else:
                    row["value"] = vals
            out.append(row)
        return out

    def _validate_site_id(site_id):
        """
        Validate site_id and raise if invalid.

        Args:
            site_id (str|int): Site identifier to validate.

        Raises:
            ParameterError: If site_id is missing or not a string/integer.

        Note:
            Internal SDK function
        """
        if not isinstance(site_id, (str, int)) or not site_id:
            raise ParameterError(
                "site_id is required and must be a string or integer"
            )
