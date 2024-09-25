# Content Infrastructure 0.0.8 (2024-09-25)

### Bugfixes

- avoid extract content-test-conf in run validations job

### Deprecations and Removals

- Removed the section of `Validate content-test-conf Branch Merged`, under `run-validations-new-validate-flow` job, because it is already under `validate-content-conf` job.
  Removed the run of `demisto-sdk secrets`, because it runs under content pre-commit GitHub action. ([CIAC-11737](https://jira-dc.paloaltonetworks.com/browse/CIAC-11737))


# Content Infrastructure 0.0.7 (2024-09-24)

### Features

- Creating API keys on demand for build machines. ([CIAC-11043](https://jira-dc.paloaltonetworks.com/browse/CIAC-11043))
- Added Playbook Flow Test to collection step
  Changed copying of content-test-conf to all servers ([CIAC-11068](https://jira-dc.paloaltonetworks.com/browse/CIAC-11068))
- Added native nightly ([CIAC-11408](https://jira-dc.paloaltonetworks.com/browse/CIAC-11408))
- splitted the run-pre-commit job into 4 seperated jobs that will run in parallel. Each job runs the pre-commit in docker tests in a different docker container which is determined according to one of the follwing options: `from-yml`, `native:ga`, `native:maintenance`, `native:candidate`. ([CIAC-11452](https://jira-dc.paloaltonetworks.com/browse/CIAC-11452))
- update-demisto-sdk-version to 1.32.1

### Bugfixes

- A tag has been added to the GitLab runner in the SDK nightly build. ([CIAC-11840](https://jira-dc.paloaltonetworks.com/browse/CIAC-11840))
- deleting datasets one at a time, to avoid issues with okta.

### Improved Documentation

- Improve the changelogs readme, mention the possiblity to use `+` when there's no issue

### Deprecations and Removals

- Removed the Connection content item type, following a removal on the SDK repo side. ([CIAC-11822](https://jira-dc.paloaltonetworks.com/browse/CIAC-11822))

### Misc

- Update report message when API key is deleted to warning.


# Content Infrastructure 0.0.6 (2024-09-19)

### Features

- Divide the CI bucket into separate buckets per marketplace.

### Bugfixes

- Updated the build-machine-cleanup flow to use the GitLab runner tag instead of a Service Account. ([CIAC-11828](https://jira-dc.paloaltonetworks.com/browse/CIAC-11828))
- fix mypy error flaky for google.cloud library


# Content Infrastructure 0.0.5 (2024-09-12)

### Features

- Added a retry mechanism when searching for Jira issues as part of the Test Modeling Rule Report.
  Jira API calls are now configured with a custom user agent.
- build machine report
- simplifying force merge builds

### Bugfixes

- Avoid stopping running when test_module command crashed
- Increased job memory of run-validations-new-validate-flow step
- fix stop running pipelines after the sub-pipeline feature broken it.
- increase --max_bad_records arg to allowed bad records to skip
- support XDR in build machines report when connecting to viso.

### Improved Documentation

- Fixed docs of bypass url to not include the public prefix.
- Improved the docs of bypass.url

### Misc

- Excluded the dataset manual_generic_alert_raw from the deletion process.
- Increased job memory of multiple nightly SDK prepare testing buckets.
- Updated Demisto-SDK to 1.31.11


# Content Infrastructure 0.0.4 (2024-09-02)

### Features

- alerting when platform,flow type is running multiple server versions.
- remove backward compatibility with XSIAM/NG server files

### Bugfixes

- Increased job memory of run-validations step

### Deprecations and Removals

- removed some leftovers related to private ([CIAC-11379](https://jira-dc.paloaltonetworks.com/browse/CIAC-11379))

### Misc

- Locking core packs for version 8.8.0 ([CIAC-11671](https://jira-dc.paloaltonetworks.com/browse/CIAC-11671))
- Increased job memory of generic-prepare-testing-bucket step
- Silence curl request in script to trigger content nightly build.
  Add .envrc to gitignore.


# Content Infrastructure 0.0.3 (2024-08-28)

### Bugfixes

- Fixed an issue where releasing infra would fail pushing to gitlab ([CIAC-11621](https://jira-dc.paloaltonetworks.com/browse/CIAC-11621))
- Fixed an issue where the filter_envs.json output was incorrect.
- Hard code hybrid packs, since querying the graph using multi-threading can lead to unresolved searches for some threads.
- fixed the CODEOWNERS syntax to match GitLab's
- fixing build report machine type
- fixing cases where the slack message is over 2000 chars limit
- fixing upload flow workflow name and addressing upload variables only as "true" or "false"

### Improved Documentation

- Improved the infra release README - command mentioned wasn't complete

### Misc

- Added a value to ignore in secrets detection
- Added the -q flag to use gsutil in quite mode
- In the infra release script, added a `-ref` argument name to the commit hash released from.
- Updated Demisto-SDK to 1.31.10
- merging the build-effort machines pool into the nightly pool


# Content Infrastructure 0.0.2 (2024-08-25)

### Features

- Added ShellCheck to pre-commit ([CIAC-6353](https://jira-dc.paloaltonetworks.com/browse/CIAC-6353))
- Added a trigger to the sync all buckets pipeline in Jenkins in the 'sync-buckets-between-projects' job ([CIAC-10377](https://jira-dc.paloaltonetworks.com/browse/CIAC-10377))
- Split the testing of modeling rules on XSIAM to multiple machines ([CIAC-11145](https://jira-dc.paloaltonetworks.com/browse/CIAC-11145))
- CIAC-11303 Improve cleanup schedule pipeline ([CIAC-11303](https://jira-dc.paloaltonetworks.com/browse/CIAC-11303))
- in clonse_repository_with_fallback_branch, search for existing tags (and not only existing branches), for cloning infra in content builds. ([CIAC-11473](https://jira-dc.paloaltonetworks.com/browse/CIAC-11473))
- Copied Content Gold (content-internal-dist) Python dependencies into a dedicated, optional group in `pyproject.toml`. Gold will now use Infra's pyproject. ([CIAC-11495](https://jira-dc.paloaltonetworks.com/browse/CIAC-11495))
- Changed infra to not trigger a test-upload-flow when content's pyproject.toml, poetry.lock or poetry.toml are modified ([CIAC-11507](https://jira-dc.paloaltonetworks.com/browse/CIAC-11507))
- https://jira-dc.paloaltonetworks.com/browse/CIAC-11532
  trigger content builds as a sub-pipeline instead of detached pipeline ([CIAC-11532](https://jira-dc.paloaltonetworks.com/browse/CIAC-11532))
- Add licenses information into build machines report
- Added support for copy relative path images.
- Adding bootstrap script to infra
- report missing users in the name mapping

### Bugfixes

- Removed the deprecated `types-pkg-resources` package dependency. We will use the `types-setuptools` package instead. Downgraded matplotlib to 3.9.0, as 3.9.1 was yanked. ([CIAC-11458](https://jira-dc.paloaltonetworks.com/browse/CIAC-11458))
- Fix an issue where the ***Test Native Candidate*** pipeline fails if the **mypy** dependency is not installed. ([CIAC-11468](https://jira-dc.paloaltonetworks.com/browse/CIAC-11468))
- Fail the upload flow if the current commit is behind the last upload commit. ([CIAC-11475](https://jira-dc.paloaltonetworks.com/browse/CIAC-11475))
- Fixed an issue where shellcheck failed in master. For more info, see the Jira issue. ([CIAC-11508](https://jira-dc.paloaltonetworks.com/browse/CIAC-11508))
- Added authenticate with Docker before running pre-commit. ([CIAC-11590](https://jira-dc.paloaltonetworks.com/browse/CIAC-11590))
- fix Okta login, code taken from Rocket repository
- fix build report user agent
- fix npm installation error

### Improved Documentation

- Documented the process of releasing an infra version ([CIAC-9545](https://jira-dc.paloaltonetworks.com/browse/CIAC-9545))
- documented using towncrier ([CIAC-11444](https://jira-dc.paloaltonetworks.com/browse/CIAC-11444))
- Improve README for the Changelog folder to provide clearer instructions. ([CIAC-11470](https://jira-dc.paloaltonetworks.com/browse/CIAC-11470))
- Improved the logs of the test integration instance runs.

### Deprecations and Removals

- Removed the automated _release-opening_ process (keeping only the release commit creation), see `infra_release/README.md`. ([CIAC-9545](https://jira-dc.paloaltonetworks.com/browse/CIAC-9545))
- Reduced the value of JIRA_MAX_TEST_PLAYBOOKS_FAILURES_TO_HANDLE ([CIAC-11163](https://jira-dc.paloaltonetworks.com/browse/CIAC-11163))

### Misc

- [CIAC-10677](https://jira-dc.paloaltonetworks.com/browse/CIAC-10677), [CIAC-11495](https://jira-dc.paloaltonetworks.com/browse/CIAC-11495), [419](https://jira-dc.paloaltonetworks.com/browse/419), [447](https://jira-dc.paloaltonetworks.com/browse/447)


# Content Infrastructure 0.0.1 (2024-08-04)

### Features

- Created a versioning mechanism ([CIAC-9545](https://jira-dc.paloaltonetworks.com/browse/CIAC-9545))
