#!/bin/bash
# Start HAL Stream System

echo "Starting HAL Stream System..."

# Check if MQTT is running
if ! pgrep -x "mosquitto" > /dev/null; then
    echo "Starting Mosquitto MQTT broker..."
    mosquitto -d
    sleep 2
fi

# Start the stream engine
echo "Starting stream engine..."
python3 /home/hal/HALbridge/hal_stream_final.py --auto-start &

# Wait a moment
sleep 3

# Start the UI
echo "Starting UI..."
python3 /home/hal/HALbridge/hal_ui_simple.py

echo "HAL System running!"
