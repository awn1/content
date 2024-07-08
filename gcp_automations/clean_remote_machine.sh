# Usage: clean_remote_machine.sh --zone [zone] --tenant-id [tentnat-id]

zone=zone
tenant_id=12345

while [[ "$#" -gt 0 ]]; do
    case "${1}" in
        --zone) zone="${2}"; shift ;;
        --tenant-id) tenant_id="${2}"; shift ;;
        *) echo "Unknown option: ${1}" ;;
    esac
    shift
done

echo Cleaning tenant ${tenant_id} in zone ${zone}

gcloud container clusters get-credentials engine-cluster-${tenant_id} --zone ${zone} --project engine-qa2-test-${tenant_id}

kubectl get pods -n xdr-st | grep engine | for i in `awk {'print $1'}` ; do
kubectl exec -it -n xdr-st $i -- /bin/sh <<'ENDSSH'
date
podman image ls | wc; df -h; podman rmi $(podman images -aq); podman image ls | wc; df -h
date
ENDSSH
done

