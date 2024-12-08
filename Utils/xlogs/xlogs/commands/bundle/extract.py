import io
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path


def recursively_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    """
    Recursively extracts the contents of a tar archive, including nested .gz files.

    Note:
        This function modifies the 'name' attribute of each TarInfo object to avoid
        issues with absolute paths in the archive.
    """

    for file in tar.getmembers():
        path = Path(file.path)

        file.name = path.name  # required since file names start with `/home/...` and it confuses Python

        if path.suffix == ".gz":
            recursively_extract_tar(tarfile.open(fileobj=tar.extractfile(file)), dest / path.stem)
        else:
            tar.extract(file, dest)


def extract(zip_bytes: bytes, dest: Path, bundle_password: str):
    """
    Extracts a password-protected zip file containing a tar archive.

        This function takes a byte string representing a zip file, extracts its contents
        (which is expected to be a single tar archive), and then recursively extracts
        the contents of the tar archive to the specified destination.

        Note:
            The zip file is expected to contain a single tar archive. The tar archive
            can contain nested .gz files, which will be recursively extracted.
    """
    with (
        zipfile.ZipFile(BytesIO(zip_bytes)) as zip,
        tarfile.open(fileobj=io.BytesIO(zip.read(zip.namelist()[0], pwd=bundle_password.encode()))) as tar,
    ):
        recursively_extract_tar(tar, dest)
