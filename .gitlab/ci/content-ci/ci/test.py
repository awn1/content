import json
import yaml


def generate_gitlab_ci():
    machines = {'1': 'test',
                '2': 'test2, test3'}

    gitlab_ci = {
        'stages': ['test'],
        'variables': {
            'MACHINE_MAPPING': json.dumps(machines)
        },
        'test': {
            'stage': 'test',
            'parallel': {
                'matrix': []
            },
            'script': [
                'echo Running tests on $MACHINE_ID',
                'echo $TESTS'
            ]
        }
    }

    for machine_id, tests in machines.items():
        job = {
            'MACHINE_ID': machine_id,
            'TESTS': ' '.join(tests)
        }
        gitlab_ci['test']['parallel']['matrix'].append(job)

    with open('.gitlab-ci.yml', 'w') as file:
        yaml.dump(gitlab_ci, file, default_flow_style=False)


if __name__ == "__main__":
    generate_gitlab_ci()
