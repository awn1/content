# Upload content-graph data to BigQuery
The purpose of the `Tests/Marketplace/upload_marketplace_data_to_bigquery.py` script - is to retrieve content items' metadata from neo4j content graph, and upload it to a BigQuery dataset as a datasource for `Marketplace Analytics Dashboard`.

This script (`upload_marketplace_data_to_bigquery.py`) is intended to run within a dedicated CI step (`upload-content-graph-data-to-bigquery`) within the `Upload Flow` pipeline, in order to reflect a snapshot of the current marketplaces' content items data.

## Prerequisites
- `demisto-sdk`
- `gcloud`

In order to run the `upload_marketplace_data_to_bigquery.py` script, the executing environment has to be privileaged with write&read permissions to the BigQuery dataset `xsoar-content-build.marketplace_analytics`, in addition to a Neo4j content-graph instance running within this environment, whether it is local dev environment or on a CI machine.

## Execution

Make sure a content graph instance is alive:
Run ```demisto-sdk graph update``` in content repo - alternatively start it from a cached version ```demisto-sdk graph update -i <PATH_TO_GRAPH_ZIP>```

Run the script with:
```python3 ./Tests/Marketplace/upload_marketplace_data_tp_bigquery```


### Confluence page

[Marketplace Content Analytics Dashboard](https://confluence-dc.paloaltonetworks.com/display/DemistoContent/Marketplace+Content+Analytics+Dashboard)