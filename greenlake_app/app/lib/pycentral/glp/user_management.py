# (C) Copyright 2025 Hewlett Packard Enterprise Development LP.
# MIT License

from ..utils import GLP_URLS, generate_url


class UserMgmt(object):
    def get_users(self, conn, filter=None, limit=300, offset=0):
        """Retrieve users that match given filters.

        All users are returned when no filters are provided. The Get users API can be filtered by:
        id, username, userStatus, createdAt, updatedAt, lastLogin.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            filter (str, optional): Filter data using a subset of OData 4.0 and return only the subset of
                resources that match the filter. Examples:

                - Filter with id: filter=id eq '7600415a-8876-5722-9f3c-b0fd11112283'
                - Filter with username: filter=username eq 'user@example.com'
                - Filter with userStatus: filter=userStatus neq 'UNVERIFIED'
                - Filter with createdAt: filter=createdAt gt '2020-09-21T14:19:09.769747'
                - Filter with updatedAt: filter=updatedAt gt '2020-09-21T14:19:09.769747'
                - Filter with lastLogin: filter=lastLogin lt '2020-09-21T14:19:09.769747'
            limit (int, optional): Specify the maximum number of entries per page. Maximum value accepted is 300. Range: 1-300.
            offset (int, optional): Specify pagination offset. Defines how many pages to skip before returning results. 

        Returns:
            (dict): API response containing users.
        """
        conn.logger.info("Getting users in GLP workspace")
        path = generate_url(
            GLP_URLS["USER_MANAGEMENT"], category="user_management"
        )

        params = {
            "limit": limit,
            "offset": offset,
        }
        if filter:
            params["filter"] = filter

        resp = conn.command(
            api_method="GET", api_path=path, api_params=params, app_name="glp"
        )
        return resp

    def get_user(self, conn, email=None, id=None):
        """Get a user from a workspace.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            email (str, optional): Account username (email address).
            id (str, optional): Target user ID.

        Returns:
            (dict): Response as provided by 'command' function in NewCentralBase.
        """
        conn.logger.info("Getting a user in GLP workspace")
        if email:
            id = self.get_user_id(conn, email)[1]

        path = generate_url(
            f"{GLP_URLS['USER_MANAGEMENT']}/{id}", category="user_management"
        )

        resp = conn.command("GET", path, "glp")
        if resp["code"] == 200:
            conn.logger.info("Get user successful!")
        else:
            conn.logger.error("Get user failed!")
        return resp

    def get_user_id(self, conn, email):
        """Get user ID in a GLP workspace by email.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            email (str): Account username (email address).

        Returns:
            (tuple(bool, str)): Tuple of two elements. First element returns True if user ID is found,
                else False. The second element is a GLP user ID if found, else an error message.
        """

        filter = f"username eq '{email}'"
        resp = self.get_users(conn, filter=filter)
        if resp["code"] != 200:
            return (resp, (False, "Bad request for get_id"))
        elif resp["msg"]["count"] == 0:
            return (False, "Email not found")
        else:
            return (True, resp["msg"]["items"][0]["id"])

    def delete_user(self, conn, email=None, user_id=None):
        """Delete a user from a workspace.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            email (str, optional): Account username (email address).
            user_id (str, optional): Target user ID.

        Returns:
            (dict): API response from the delete operation.
        """
        conn.logger.info("Deleting a user in GLP workspace")
        if email:
            user_id = self.get_user_id(conn, email)[1]

        path = generate_url(
            f"{GLP_URLS['USER_MANAGEMENT']}/{user_id}",
            category="user_management",
        )
        resp = conn.command(api_method="DELETE", api_path=path, app_name="glp")
        return resp

    def inv_user(self, conn, email, send_link):
        """Invite a user to a GLP workspace.

        Args:
            conn (NewCentralBase): pycentral base connection object.
            email (str): Email address of the user to invite.
            send_link (bool): Set to True to send welcome email.

        Returns:
            (dict): Response as provided by 'command' function in NewCentralBase.
        """
        conn.logger.info("Inviting a user to GLP workspace")

        path = generate_url(
            GLP_URLS["USER_MANAGEMENT"], category="user_management"
        )
        body = {"email": email, "sendWelcomeEmail": send_link}

        resp = conn.command("POST", path, "glp", api_data=body)
        if resp["code"] == 201:
            conn.logger.info("Invite user successful!")
        else:
            conn.logger.error("Invite user failed!")
        return resp
