# Content Infrastructure 0.0.28 (2025-02-12)

### Features

- Added support for sending blacklist validation Slack messages only under specific conditions. ([8885](https://jira-dc.paloaltonetworks.com/browse/8885))
- Added two more secrets to the blacklist validation flow.
- Adding logs to the search_and_install_packs function in case an invalid API response is returned.
- All scripts related to creating new disposable tenants have been moved to the creating_disposable_tenants folder.
- Fix poetry install.

### Misc

- [CIAC-12665](https://jira-dc.paloaltonetworks.com/browse/CIAC-12665)


# Content Infrastructure 0.0.27 (2025-02-04)

### Features

- Added the "enabled" arg to the create_disposable_tenants script.
- New secript wait_disposable_tenants_ready.
- Updated the demisto-sdk version 1.35.0 in Infra.

### Bugfixes

- Fixed the update_tenant_configmap script with added configmap for XSIAM.


# Content Infrastructure 0.0.26 (2025-02-03)

### Bugfixes

- Revert "add support in authenticate tag".


# Content Infrastructure 0.0.25 (2025-01-30)

### Features

- New script create_disposable_tenants. ([CIAC-12689](https://jira-dc.paloaltonetworks.com/browse/CIAC-12689))
- New script update_tenant_configmap. ([CIAC-12731](https://jira-dc.paloaltonetworks.com/browse/CIAC-12731))
- Added the ***cortex-content-1738*** tag, which binds to an identifier that enables GitLab runners to access Google resources. This tag replaces the need for manual authentication via the gcloud library. ([11348](https://jira-dc.paloaltonetworks.com/browse/11348))

### Bugfixes

- Fixed a bug where the slack notification failed when the DRY_RUN parameter was not supplied. ([738](https://jira-dc.paloaltonetworks.com/browse/738))
- Fix issue with the imports in build_machines_report.py file.


# Content Infrastructure 0.0.24 (2025-01-28)

### Features

- Created a new pipeline for deploy the auto upgrade packs config file into the buckets. ([CIAC-1226](https://jira-dc.paloaltonetworks.com/browse/CIAC-1226))
- Update pre-commit pycln hook version to 2.5.0.
- Updated the demisto-sdk version 1.34.1 in Infra.

### Bugfixes

- Fixed an issue where duplicate lines were created if the machine was not connected.
- Fixed an issue where tenants server version that were not parsed correctly in the build_machine_report caused the build to fail.
- changed the command examples files names to the new standard 'command_examples.txt'

### Improved Documentation

- Fixed a typo in the Content infrastructure versioning README file.
- Update code owner on build to Menachem.


# Content Infrastructure 0.0.23 (2025-01-22)

### Features

- Reintroduce demisto-sdk to the new docker registry proxy. ([CIAC-11589](https://jira-dc.paloaltonetworks.com/browse/CIAC-11589))
- Updated the demisto-sdk version 1.34.0 in Infra.

### Bugfixes

- Configure the uninstall-packs-and-reset-bucket-cloud-all-packs job with the argument --all-packs.

### Deprecations and Removals

- Removed CommonServerPython from running with pre-commit -a (should pre-commit all). ([CIAC-9569](https://jira-dc.paloaltonetworks.com/browse/CIAC-9569))


# Content Infrastructure 0.0.22 (2025-01-21)

### Features

- updated docker image in the dockerfiles build ([12391](https://jira-dc.paloaltonetworks.com/browse/12391))
- Increasing timeout for the build-machines-cleanup job to 5 hours and 30 minutes.
- Updated the demisto-sdk version 1.33.6 in Infra.

### Bugfixes

- Added that when searching for pull requests in GithubClient, it will only search for PRs whose base is master (excluding PRs of contributions).


# Content Infrastructure 0.0.21 (2025-01-16)

### Features

- Use Google Secret filtering based on secret labels, instead of filtering them after getting all secrets.
  Save only the relevant secrets to a file under the "Install Packs and run Test-Module" section, instead of saving all secrets under the "Secrets Fetch" section. ([CIAC-11834](https://jira-dc.paloaltonetworks.com/browse/CIAC-11834))
- long running tag for gitlab jobs ([CIAC-12370](https://jira-dc.paloaltonetworks.com/browse/CIAC-12370))
- Added the ability to trigger the SDK release from the Gitlab UI. ([CIAC-12459](https://jira-dc.paloaltonetworks.com/browse/CIAC-12459))
- Added that if the *.pre-commit-config_template.yaml* file is been changed, then *pre-commit* will run in all files mode.
- Updated the demisto-sdk version 1.33.5 in Infra.

### Bugfixes

- Fixed an issue where copy prod bucket to machine bucket failed. ([CIAC-12510](https://jira-dc.paloaltonetworks.com/browse/CIAC-12510))
- In content-docs if build-docusaurus fails exit with an error.

### Deprecations and Removals

- Removed support for the redundant `secret_id` label for Google Secrets.
  Removed duplicate `project_id` argument for some functions in `GoogleSecreteManagerModule`. ([CIAC-10891](https://jira-dc.paloaltonetworks.com/browse/CIAC-10891))


# Content Infrastructure 0.0.20 (2025-01-07)

### Features

- Updated the demisto-sdk version 1.33.4 in Infra. ([sdk_1_33_4](https://jira-dc.paloaltonetworks.com/browse/sdk_1_33_4))

### Bugfixes

- Add *_request_timeout* every time we call *generic_request_func*.

### Improved Documentation

- Updated the README file. ([update_readme](https://jira-dc.paloaltonetworks.com/browse/update_readme))
- Improved the Triggers documentation. ([CIAC-11406](https://jira-dc.paloaltonetworks.com/browse/CIAC-11406))


# Content Infrastructure 0.0.19 (2025-01-05)

### Features

- Updated the flow-type of NG nightly machines.

### Misc

- [CIAC-12343](https://jira-dc.paloaltonetworks.com/browse/CIAC-12343)


# Content Infrastructure 0.0.18 (2025-01-01)

### Features

- Updated the demisto-sdk version 1.33.3 in Infra.

### Bugfixes

- Moved a missing trigger script from dockerfiles-cicd repo to Infra.

### Deprecations and Removals

- Removed the native image from the pre-commit steps. ([12513](https://jira-dc.paloaltonetworks.com/browse/12513))


# Content Infrastructure 0.0.17 (2024-12-31)

### Features

- Updated the demisto-sdk version 1.33.2 in Infra.

### Bugfixes

- Fixed an issue where the build didn't fail when unable to sync marketplace. ([CIAC-12353](https://jira-dc.paloaltonetworks.com/browse/CIAC-12353))


# Content Infrastructure 0.0.16 (2024-12-25)

### Features

- Auto update docker build

### Bugfixes

- Fixed an authentication issue in the demisto-sdk release caused by using the wrong variable throughout the pipeline.


# Content Infrastructure 0.0.15 (2024-12-24)

### Features

- Added the **ask-permissions** command in the **xlogs** project.

### Bugfixes

- Fix an authentication issue in the demisto-sdk release caused by using the wrong variable.
- Removed unnecessary variables from trigger-contribution-build flow.
- fix pushed docker path

### Deprecations and Removals

- Removed Dor's code ownerships

### Misc

- Add logs to the search and install packs process
- Added values to the secrets ignore list.


# Content Infrastructure 0.0.14 (2024-12-10)

### Features

- Migrate Dockerfiles CircleCI workflows to GitHub Actions ([CIAC-7077](https://jira-dc.paloaltonetworks.com/browse/CIAC-7077))
- Add support for the version_config.json file in upload. ([CIAC-12327](https://jira-dc.paloaltonetworks.com/browse/CIAC-12327))
- Added the **xlogs** project (under Utils/xlogs)
- Changed the JIRA_MAX_TEST_PLAYBOOKS_FAILURES_TO_HANDLE_DEFAULT from 20 to 25.
- Updated the demisto-sdk version 1.33.0 in Infra.


# Content Infrastructure 0.0.13 (2024-12-05)

### Features

- Added support for the override-content pipeline ([CIAC-11762](https://jira-dc.paloaltonetworks.com/browse/CIAC-11762))
- Reduce index.zip file size ([CIAC-12307](https://jira-dc.paloaltonetworks.com/browse/CIAC-12307))
- Add an option to ignore specific flow-type in the build machines report.
- Enhanced the automated Demisto-SDK release process to automatically generate a merge request in Infra to update the new version.
- Support other group machines in the build machines report, by not deleting their API keys from GSM.
- move content docs build to gitlab

### Bugfixes

- Fix force upload build
- Fix force upload issue with packs path

### Deprecations and Removals

- Removing the 'replace xsoar' mechanism from infra (now implemented in prepare_content instead). ([10198](https://jira-dc.paloaltonetworks.com/browse/10198))


# Content Infrastructure 0.0.12 (2024-11-25)

### Features

- Created a new pipeline for overriding core packs lists. ([11298](https://jira-dc.paloaltonetworks.com/browse/11298))
- Updated the sdk version 1.32.5 in Infra.

### Bugfixes

- Fixed an issue where corepacks files are not copied to the build bucket. ([12002](https://jira-dc.paloaltonetworks.com/browse/12002))
- Revert ciac-11348 - since it fails the content logs processing.
- Timeout issues - removed search for hybrid packs.

### Misc

- Added the --quiet flag to disable all interactive prompts when running gcloud commands.


# Content Infrastructure 0.0.11 (2024-11-13)

### Features

- Added a pack by pack retry mechanism on bulk batch installation failures. ([CIAC-11299](https://jira-dc.paloaltonetworks.com/browse/CIAC-11299))
- Modified the `create_release` script which would previously generate all release notes of the `demisto-sdk` in one section. Now it generates the changelog with different sections separated by headers Fixed, Breaking Changes, and Internal. ([CIAC-11845](https://jira-dc.paloaltonetworks.com/browse/CIAC-11845))
- Removing the Slack notification for build pivots and replacing the blacklist validation notification with a GitLab Slack notification. ([10874](https://jira-dc.paloaltonetworks.com/browse/10874))
- Bump demisto-sdk to version 1.32.4.

### Bugfixes

- Change batch pack installation retries from 5 to 3. ([CIAC-11299](https://jira-dc.paloaltonetworks.com/browse/CIAC-11299))

### Misc

- Added values to the secrets ignore list.
- Removed stacktrace from build machine report for when creating an API key is unsuccessful.
- Updated the deprecated graph update command in the on-push pipeline to use the latest.
- added support to copy neo4j into artifacts in the build-machines cleanup afterscript.


# Content Infrastructure 0.0.10 (2024-11-03)

### Features

- Bump demisto-sdk to version 1.32.3.
- Remove demisto-sdk support using a DockerHub proxy from GAR when running in a Gitlab CI environment.

### Bugfixes

- Added docker authentication to update-content-graph job to allow initialising a docker daemon using the job's service account. ([CIAC-11589](https://jira-dc.paloaltonetworks.com/browse/CIAC-11589))
- Fixed the timing of the step sync-bucket-between-projects to start after the upload steps are completed. ([CIAC-11965](https://jira-dc.paloaltonetworks.com/browse/CIAC-11965))
- Fixed an issue where content items of type *Triggers Recommendations* were being filtered out during the upload process. ([CIAC-12002](https://jira-dc.paloaltonetworks.com/browse/CIAC-12002))
- Fixing an issue where the Content Graph Interface failed in a multi-threaded environment due to an inability to create multiple interfaces at the same time. ([11638](https://jira-dc.paloaltonetworks.com/browse/11638))
- Added better handling for cases where slack notifier fails to get trigger-test-upload report.
- Added cleanup for pack's doc_files folder after relative image path upload.
- Fixed an issue where error appeared in Installing Virtualenv step due to missing exit_code.

### Deprecations and Removals

- Removed the update-validation-docs step from the demisto-sdk release flow ([CIAC-11879](https://jira-dc.paloaltonetworks.com/browse/CIAC-11879))


# Content Infrastructure 0.0.9 (2024-10-07)

### Features

- Enhanced pre- / post-update instance testing. ([CIAC-11059](https://jira-dc.paloaltonetworks.com/browse/CIAC-11059))
- demisto-sdk now supports using a DockerHub proxy from GAR when running in a Gitlab CI environment. ([CIAC-11589](https://jira-dc.paloaltonetworks.com/browse/CIAC-11589))

### Bugfixes

- Fixed a issue where the upload core files script failed because of querying the wrong bucket. ([132353](https://jira-dc.paloaltonetworks.com/browse/132353))
- Added better handling for test-upload-flow pipeline creation failures.
- Raised timeout for cleanup step.
- fixing an issue where the missing users in the mapping wasn't returned

### Misc

- [CIAC-11751](https://jira-dc.paloaltonetworks.com/browse/CIAC-11751)
- Added `shfmt`
- Added a `poetry.toml` to the infra repo. This tells `Poetry` to always create the virtual environments in the project directory (rather than `/.cache/pypoetry`)
- Added values to the secrets ignore list.
- demisto-sdk release 1.32.2.


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
