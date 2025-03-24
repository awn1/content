# Content infrastructure versioning

## How to release an Infra version
1.  Get a commit hash you want to release.
    Make sure nightly has already passed on the commit hash! Otherwise, the release may break.
2.  Run `poetry run python .gitlab/ci/ci_resources/infra-release-ci/release_infra.py` with the necessary arguments. _(add ` --help` for more information)_
3.  A new branch `infra_v0.0.0` (matching your version) will be pushed & merge request will be created. Go to the infra repo _merge requests_ section, and ask a TL/manager to approve it.
4.  Merge to master. Check  https://gitlab.xdr.pan.local/xdr/cortex-content/infra/-/commits/master/?ref_type=HEADS. You'll see two commits under your name. Copy the commit sha of the earlier one (NOT the `Merge branch...` one).
5.  Go to https://gitlab.xdr.pan.local/xdr/cortex-content/infra/-/releases/new. Type in a new tag `v0.0.0` and then the commit hash you copied in the previous step (don't use the default `master`). Choose Release title=`Infra v0.0.0`. Copy the top of `CHANGELOG.md` (the changes included in your release) to the `Description` field. Click `Create Release`.
6. Ask a GitLab maintainer (manager/principal eng.) to update the `INFRA_BRANCH` to the `v0.0.0` you just released, and Voilà!
in [cortext-content gitlab project:](https://gitlab.xdr.pan.local/groups/xdr/cortex-content)
setting>cicd ->variables->search INFRA_BRANCH


## Hotfixing
Hotfixing is the process of creating a release with a temporary fix, that isn't intended to be merged.

Do the same as above, but:
- In step 4, do not merge to master.
- In step 5, just use the commit sha that was printed at the end of step 2. (The commit that was automatically created with the release branch )