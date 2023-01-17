#!/bin/bash
MITMDUMP_ENV_FILE=/home/gcp-user/mitmdump_rc

#Validating env variable file exists
if [ -f $MITMDUMP_ENV_FILE ];
then
  echo "$MITMDUMP_ENV_FILE content:"
  cat $MITMDUMP_ENV_FILE
  source $MITMDUMP_ENV_FILE
  else
    echo "Could not find $MITMDUMP_ENV_FILE file"
    exit 1
fi
#Validating env variables exist
if [ -z "$SCRIPT_MODE" ];
then
  echo "SCRIPT_MODE env variable was not found"
  exit 2
fi

if [ -z "$KEYS_FILE_PATH" ];
then
  echo "KEYS_FILE_PATH env variable was not found"
  exit 2
fi

if [ -z "$MOCK_FILE_PATH" ];
then
  echo "MOCK_FILE_PATH env variable was not found"
  exit 2
fi

if [ -z "$LOG_FILE_PATH" ];
then
  echo "LOG_FILE_PATH env variable was not found"
  exit 2
fi

if [[ ! -f "$LOG_FILE_PATH" ]]
then
  echo "log file in path $LOG_FILE_PATH does not exist, creating it"
  mkdir -p `dirname "$LOG_FILE_PATH"`
  touch "$LOG_FILE_PATH"
fi


if [[ "$SCRIPT_MODE" == "playback" ]];
  then
    echo "Starting mitmdump in playback mode"
    /home/gcp-user/.local/bin/mitmdump --ssl-insecure --verbose --listen-port 9997 -s /home/gcp-user/timestamp_replacer.py --set script_mode="$SCRIPT_MODE" --set keys_filepath="$KEYS_FILE_PATH" --set keepserving=true --server-replay-kill-extra --server-replay "$MOCK_FILE_PATH" | tee "$LOG_FILE_PATH" 2>&1
    echo "Exited with status code $?"

elif [[ "$SCRIPT_MODE" == "record" ]];
  then
    echo "Starting mitmdump in record mode"
    /home/gcp-user/.local/bin/mitmdump --ssl-insecure --verbose --listen-port 9997 -s /home/gcp-user/timestamp_replacer.py --set script_mode="$SCRIPT_MODE" --set keys_filepath="$KEYS_FILE_PATH" --set detect_timestamps=true --save-stream-file "$MOCK_FILE_PATH" | tee "$LOG_FILE_PATH" 2>&1
    echo "Exited with status code $?"

else
  echo "SCRIPT_MODE $SCRIPT_MODE not supported"
fi
