#!/bin/bash

# The following script is based on a server script and includes assumptions on log locations inside pods.
# To use this visit: https://confluence.paloaltonetworks.com/display/DemistoContent/live+integration-instance.log+when+debugging+in+XSIAM

pod=$(kubectl get pods -n xdr-st -o json | jq -c '.items[].metadata.name | select(contains("xsoar"))' | tr -d '\"')
prefix=$(date +%F_%H-%M-%S)
dir="$HOME/Downloads/pod-logs/logs"
log_filename="server.log"
logs_location="/var/log/demisto"

Copy() {
    [ -d "$dir" ] || mkdir -p "$dir"
    echo "Coping $pod:$logs_location to $dir/$prefix"
    kubectl -n xdr-st cp "$pod:$logs_location" "$dir/$prefix"
}

Live(){
    echo "Fetching $log_filename live..."
    kubectl -n xdr-st exec -i -t "$pod" -- tail -f "$logs_location/$log_filename"
}

Help() {
    echo "
        Get logs from you kubctl xsoar pod

        Syntax: bash ./get_logs.sh [options]
        options:
        -h              default - show this help
        -l <filename>     show <filename> live, default is server.log
        -c              copy logs to $dir
    "
}

if [ -z "$1" ]; then
    Help
    exit;
fi

while getopts "hlc" option; do
    case $option in
        h)
            Help
            exit;;
        l)
            [ -z "$2" ] || log_filename="$2"
            Live;;
        c)
            Copy
            exit;;
        \?)
            echo "Error: Invalid option"
            exit;;
    esac
done