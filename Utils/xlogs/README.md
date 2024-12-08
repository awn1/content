# CLI

CLI tool for finding your way around Demisto logs easily. Uses user&#x27;s own GCP permissions

**Usage**:

```console
$ [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--install-completion`: Install completion for the current shell.
* `--show-completion`: Show completion for the current shell, to copy it or customize the installation.
* `--help`: Show this message and exit.

**Commands**:

* `bundle`: Easier access to log bundles
* `log`: Easier access to GCP logs

## `bundle`

Easier access to log bundles

**Usage**:

```console
$ bundle [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `get`: Download and recursively unzip a log...
* `instances`: Show information about integration...

### `bundle get`

Download and recursively unzip a log bundle, from a GCP project.

**Usage**:

```console
$ bundle get [OPTIONS] PROJECT_ID BUNDLE_PASSWORD [DEST_PATH_BASE]
```

**Arguments**:

* `PROJECT_ID`: GCP project ID. `engine` prefix will be removed.  [required]
* `BUNDLE_PASSWORD`: [env var: DEMISTO_BUNDLE_PASSWORD; required]
* `[DEST_PATH_BASE]`: Where to save the extracted bundle  [default: /tmp/.log-bundles]

**Options**:

* `--last-modified [%Y-%m-%d|%Y-%m-%dT%H:%M:%S|%Y-%m-%d %H:%M:%S]`
* `-1, -l, --last`: Provide to bring log bundles created on a certain date
* `--force`: Download even if bundle already exists
* `--help`: Show this message and exit.

### `bundle instances`

Show information about integration instances from a log bundle.

**Usage**:

```console
$ bundle instances [OPTIONS] BUNDLE_PASSWORD
```

**Arguments**:

* `BUNDLE_PASSWORD`: [env var: DEMISTO_BUNDLE_PASSWORD; required]

**Options**:

* `--project-id TEXT`: GCP Project ID to download a log bundle from
* `--path DIRECTORY`: Path to an extracted log bundle. Takes precedence over project ID.
* `--brand TEXT`: Filter instances by brand (case insensitive)
* `--help`: Show this message and exit.

## `log`

Easier access to GCP logs

**Usage**:

```console
$ log [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `engine`: Generate a URL to conveniently search logs...
* `tenant`: Generate a URL to conveniently search logs...

### `log engine`

Generate a URL to conveniently search logs of a given integration brand. Adds summary fields and instance&amp;brand filters.

**Usage**:

```console
$ log engine [OPTIONS] PROJECT_ID INTEGRATION_NAME
```

**Arguments**:

* `PROJECT_ID`: GCP project ID. `engine` will be prepended if the project doesn&#x27;t already start with it.  [required]
* `INTEGRATION_NAME`: An integration to filter by  [required]

**Options**:

* `--days-back INTEGER`: [default: 1]
* `--exact-integration-name / --no-exact-integration-name`: [default: no-exact-integration-name]
* `--help`: Show this message and exit.

### `log tenant`

Generate a URL to conveniently search logs of tenant integration calls.

**Usage**:

```console
$ log tenant [OPTIONS] PROJECT_ID QUERY
```

**Arguments**:

* `PROJECT_ID`: [required]
* `QUERY`: [required]

**Options**:

* `--days-back INTEGER`: [default: 30]
* `--help`: Show this message and exit.

