Grafana alerting service.
This integration was integrated and tested with version 8.0.0 of Grafana

## Configure Grafana on Cortex XSOAR

1. Navigate to **Settings** > **Integrations** > **Servers & Services**.
2. Search for Grafana.
3. Click **Add instance** to create and configure a new integration instance.

    | **Parameter** | **Description** | **Required** |
    | --- | --- | --- |
    | Server URL |  | True |
    | Username |  | True |
    | Password |  | True |
    | Use system proxy settings |  | False |
    | Trust any certificate (not secure) |  | False |
    | Maximum number of incidents to fetch | Maximum is limited to 200. | False |
    | Fetch incidents |  | False |
    | First fetch time interval |  | False |
    | Dashboard IDs to fetch | A comma-separated list of dashboard IDs. Can be found by running the "grafana-dashboards-search" command. | False |
    | Panel ID to fetch | See "help". | False |
    | Alert name to fetch |  | False |
    | States to fetch |  | False |
    | Incident type |  | False |

4. Click **Test** to validate the URLs, token, and connection.
