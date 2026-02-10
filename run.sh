#!/bin/bash

# Kill ports if running
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null

echo "🐱 Setting up Python Virtual Environment..."
cd backend
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Virtual environment created."
fi

source venv/bin/activate
python -m pip --version >/dev/null 2>&1 || {
    curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    python /tmp/get-pip.py
}
python -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    python -m pip install --break-system-packages --user -r requirements.txt || true
fi

echo "🐱 Starting VeloPerf Backend..."
if python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    python main.py &
    BACKEND_PID=$!
else
    deactivate || true
    python3 -m pip install --break-system-packages --user -r requirements.txt || true
    python3 main.py &
    BACKEND_PID=$!
fi

echo "🐱 Starting VeloPerf Frontend..."
cd ../frontend
if [ ! -d "node_modules" ]; then
    if [ -f "package-lock.json" ]; then
        npm ci || npm install
    else
        npm install
    fi
fi
npm run dev &
FRONTEND_PID=$!

echo "🚀 VeloPerf is running!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"

# Trap Ctrl+C to kill both processes
trap "kill $BACKEND_PID $FRONTEND_PID; exit" INT

wait
