# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from ..utils import GLP_URLS, generate_url
from ..utils.glp_utils import rate_limit_check, check_progress
import time

# This is the single input size limit for using the POST request endpoint for adding subscriptions.
INPUT_SIZE = 5
# This is the rate limit per minute of requests that can be processed by the POST request endpoint for adding subscriptions.
POST_RPM = 4

SUB_GET_LIMIT = 50

SUB_LIMIT = 5


class Subscriptions(object):
    def get_all_subscriptions(self, conn, select=None):
        """Get all subscriptions managed in a workspace.

        API will result in 429 if this threshold is breached.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            select (list, optional): A comma separated list of select properties to return in the response.
                By default, all properties are returned. Example: select=id,key

        Returns:
            (list[dict]): A list of all subscriptions in the workspace, or an empty list if an error occurs.
        """
        conn.logger.info("Getting all subscriptions in GLP workspace")

        limit = SUB_GET_LIMIT
        offset = 0
        count = 0
        result = []

        while True:
            resp = self.get_subscription(
                conn, limit=limit, offset=offset, select=select
            )
            if resp["code"] == 200:
                resp_message = resp["msg"]
                count += resp_message["count"]
                for subscription in resp_message["items"]:
                    result.append(subscription)
                if count == resp_message["total"]:
                    break
                else:
                    offset += limit
            else:
                conn.logger.error(
                    f"Error fetching list of subscriptions: {resp['code']} - {resp['msg']}"
                )
                result = []
                break

        return result

    def get_subscription(
        self,
        conn,
        filter=None,
        select=None,
        sort=None,
        limit=SUB_GET_LIMIT,
        offset=0,
    ):
        """Get a subscription managed in a workspace.

        Rate limits are enforced on this API. 60 requests per minute is supported per workspace.
        API will result in 429 if this threshold is breached.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            filter (str, optional): Filter expressions consisting of simple comparison operations joined by logical operators.
                Example: filter=key eq 'MHNBAP0001' and key in 'PAYHAH3YJE6THY, E91A7FDFE04D44C339'
            select (list, optional): A comma separated list of select properties to return in the response.
                By default, all properties are returned. Example: select=id,key
            sort (str, optional): A comma separated list of sort expressions. A sort expression is a property name
                optionally followed by a direction indicator asc or desc. Default is ascending order.
                Example: sort=key, quote desc
            limit (int, optional): Specifies the number of results to be returned. Default is 50. Range: 1-50.
            offset (int, optional): Specifies the zero-based resource offset to start the response from. Default is 0.

        Returns:
            (dict): API response containing subscriptions.
        """
        conn.logger.info("Getting subscriptions in GLP workspace")
        path = generate_url(GLP_URLS["SUBSCRIPTION"], category="subscriptions")

        params = {"limit": limit, "offset": offset}
        if filter:
            params["filter"] = filter
        if select:
            params["select"] = select
        if sort:
            params["sort"] = sort

        resp = conn.command(
            api_method="GET", api_path=path, api_params=params, app_name="glp"
        )
        return resp

    def get_sub_id(self, conn, key):
        """Get subscription ID in a GLP workspace based on subscription key.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            key (str): Subscription key.

        Returns:
            (tuple(bool, str)): Tuple of two elements. First element returns True if subscription ID is found,
                else False. The second element is a GLP subscription ID if found, else an error message.
        """

        filter = f"key eq '{key}'"
        resp = self.get_subscription(conn, filter=filter)
        if resp["code"] != 200:
            return (resp, (False, "Bad request for get_sub"))
        elif resp["msg"]["count"] == 0:
            return (False, "Key not found")
        else:
            return (True, resp["msg"]["items"][0]["id"])

    def get_status(self, conn, id):
        """Get status of an async GLP subscription request.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            id (str): Transaction ID from async API request.

        Returns:
            (dict): Response as provided by 'command' function in NewCentralBase.
        """

        path = generate_url(
            f"{GLP_URLS['ASYNC']}/{id}", category="subscriptions"
        )
        resp = conn.command("GET", path, "glp")
        return resp

    def add_subscription(self, conn, subscriptions=None, limit=0, offset=0):
        """Add one or more subscriptions to a workspace.

        This API provides an asynchronous response and will always return "202 Accepted" if basic input
        validations are successful. The location header in the response provides the URI to be invoked
        for fetching progress of the subscription addition task. For details about the status fetch URL,
        refer to the API Get progress or status of async operations in subscriptions.
        Rate limits are enforced on this API. 4 requests per minute is supported per workspace.
        API will result in 429 if this threshold is breached.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            subscriptions (list, optional): List of subscription key objects.
                Example: [{"key": "string"}]
            limit (int, optional): Specifies the number of results to be returned. Default is 0. Range: 1-50.
            offset (int, optional): Specifies the zero-based resource offset to start the response from.

        Returns:
            (dict): API response from the add subscription operation.
        """
        conn.logger.info("Adding subscription(s) to GLP workspace")
        path = generate_url(GLP_URLS["SUBSCRIPTION"], category="subscriptions")

        if len(subscriptions) > INPUT_SIZE:
            resp = []
            rate_check = rate_limit_check(subscriptions, INPUT_SIZE, POST_RPM)
            queue, wait_time = rate_check

            for i in range(len(queue)):
                params = {
                    "offset": offset,
                }

                data = {"subscriptions": queue[i]}

                time.sleep(wait_time)

                resp.append(
                    conn.command(
                        api_method="POST",
                        api_path=path,
                        api_params=params,
                        api_data=data,
                        app_name="glp",
                    )
                )

        else:
            params = {
                "offset": offset,
            }

            data = {"subscriptions": subscriptions}

            resp = conn.command(
                api_method="POST",
                api_path=path,
                api_params=params,
                api_data=data,
                app_name="glp",
            )

        if resp["code"] == 202:
            conn.logger.info(
                "Add subscription(s) to workspace request accepted..."
            )
            id = resp["msg"]["transactionId"]
            status = check_progress(conn, id, self, limit=SUB_LIMIT)
            if status[0]:
                conn.logger.info(
                    "Sucessfully added subscription(s) to workspace!"
                )
                return status[1]
            else:
                conn.logger.error("Add subscription(s) to workspace failed!")
                return status[1]
        conn.logger.error("Bad request for add subscription(s) to workspace!")
        return resp
