import sys
import re

# GCLOUD_SSH_ARGS_NAMES = ['zone', 'project', 'verbosity']
GCLOUD_SSH_FLAGS_NAMES = '(?:(?:quiet)|(?:tunnel-through-iap))'
GCLOUD_SSH_ARGS_NAMES_PATTERN = '(?:(?:zone)|(?:project)|(?:verbosity))'


def get_ssh_command_args():
    full_args = sys.argv[2:]
    general_ssh_args = []
    gcloud_ssh_args = []
    while True:
        # print(full_args)
        if full_args[0] == '-o':
            general_ssh_args.append(full_args.pop(0))
            general_ssh_args.append(full_args.pop(0))
        elif re.match(f'--(?:(?:{GCLOUD_SSH_ARGS_NAMES_PATTERN}=.+)|{GCLOUD_SSH_FLAGS_NAMES})$', full_args[0]):
            gcloud_ssh_args.append(full_args.pop(0))
        elif re.match(f'--{GCLOUD_SSH_ARGS_NAMES_PATTERN}', full_args[0]):
            gcloud_ssh_args.append(full_args.pop(0))
            gcloud_ssh_args.append(full_args.pop(0))
        elif full_args[0].startswith('-'):
            full_args.pop(0)
        else:
            host = full_args.pop(0)
            break

    gcloud_ssh_args_str = ' '.join(gcloud_ssh_args)
    general_ssh_args_str = ' '.join(general_ssh_args)
    '&)'
    command = ' '.join(full_args)
    return f'gcloud compute ssh {gcloud_ssh_args_str} gcp-user@{host} -- {general_ssh_args_str} -C {command}'


def get_scp_command_args():
    full_args = sys.argv[2:]
    ssh_args = []
    while True:
        if full_args[0] == '-o':
            full_args.pop(0)
            full_args.pop(0)
        elif full_args[0].startswith('--'):
            ssh_args.append(full_args.pop(0))
        else:
            src = full_args.pop(0)
            dest = full_args.pop(0)
            break

    if src.startswith('['):
        src = src.replace('[', '', 1).replace(']', '', 1)

    if dest.startswith('['):
        dest = dest.replace('[', '', 1).replace(']', '', 1)

    return f"gcloud compute scp {' '.join(ssh_args)} {src} {dest}"


SSH_TYPE_FUNCTION = {
    'scp': get_scp_command_args,
    'ssh': get_ssh_command_args
}


def main():
    ssh_command = sys.argv[1]
    command = SSH_TYPE_FUNCTION[ssh_command]
    print(command())


if __name__ == '__main__':
    main()
