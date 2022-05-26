#!/bin/sh

set -e
python3 -m pip install --user pipx
python3 -m pipx ensurepath
. ~/.profile
pipx install mitmproxy
pipx inject mitmproxy dateparser MarkupSafe==2.0.1