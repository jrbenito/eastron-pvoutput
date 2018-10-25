#!/bin/bash
while true; do
	python ./sdm2pvoutput.py
	echo "python script erro, sleeping few seconds and call it again"
	sleep 60s
done
