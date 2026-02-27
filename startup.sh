#!/bin/bash
set -e

echo "Starting supervisord..."
supervisord -c /home/site/wwwroot/supervisord.conf