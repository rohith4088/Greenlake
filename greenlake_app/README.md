# GreenLake Dashboard

A standalone web application to manage HPE GreenLake Devices, Subscriptions, and Users.

## Features
- **Dashboard**: Overview of your GreenLake environment.
- **Devices**: List and manage devices.
- **Subscriptions**: View subscription details.
- **Users**: Manage workspace users.
- **Modern UI**: Dark mode, glassmorphism design.

## Prerequisites
- Docker and Docker Compose
- HPE GreenLake Client ID and Client Secret

## How to Run

1.  **Build and Run with Docker Compose**:
    ```bash
    docker-compose up --build
    ```

2.  **Access the App**:
    Open your browser and navigate to `http://localhost:8000`.

3.  **Configuration**:
    - On the first load, the app will show "Not Configured".
    - Click "Configuration" in the sidebar.
    - Enter your GreenLake `Client ID` and `Client Secret`.
    - Click "Save Credentials".

## Project Structure
- `app/main.py`: Backend entry point (FastAPI).
- `app/api/`: API endpoints.
- `app/templates/`: HTML frontend.
- `app/static/`: CSS and JS assets.
- `app/lib/pycentral`: Embedded GreenLake SDK.
