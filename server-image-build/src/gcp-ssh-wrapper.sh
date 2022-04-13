#!/bin/sh

exec $(python /server-image-build/src/ssh_args_fixer.py ssh $@)