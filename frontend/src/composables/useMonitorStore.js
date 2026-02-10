import { reactive, ref } from 'vue'

// Singleton State
const state = reactive({
  dataBuffer: {
    cpu: [],
    memory: [],
    memoryDetail: [],
    fps: [],
    gpu: [],
    jank: [],
    stutter: [],
    batteryTemp: [],
    network: []
  },
  markers: [], // Array of { time: Date, label: string }
  logList: [],
  screenshotBuffer: [],
  currentScreenshot: '',
  isConnected: false,
  lastUpdated: 0, // General update
  lastMetricUpdate: 0, // Only for metrics
  lastLogUpdate: 0, // Only for logs
  currentPackage: ''
})

let ws = null
let reconnectTimer = null

export const useMonitorStore = () => {

  const connectWs = (serial, target = null) => {
    if (!serial) {
      console.warn('Store: connectWs called without serial')
      return
    }

    if (ws) ws.close()
    if (reconnectTimer) clearTimeout(reconnectTimer)

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/monitor/${serial}`
    
    console.log('Store: Connecting to WS:', wsUrl)
    ws = new WebSocket(wsUrl)
    
    ws.onopen = () => {
      console.log('Store: WS Connected')
      state.isConnected = true
      // Send start command
      const msg = target ? { type: "start", target } : { type: "start" }
      ws.send(JSON.stringify(msg))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      
      // Handle Screenshot
      if (data.type === 'screenshot') {
        state.screenshotBuffer.push({ time: data.timestamp, url: data.url })
        if (state.screenshotBuffer.length > 50) state.screenshotBuffer.shift()
        state.currentScreenshot = data.url
        return
      }

      // Handle Log
      if (data.type === 'log') {
        if (state.logList.length > 1000) state.logList.shift() // Keep 1000 logs in store
        
        const date = new Date(data.timestamp)
        const timeStr = `${date.getHours().toString().padStart(2,'0')}:${date.getMinutes().toString().padStart(2,'0')}:${date.getSeconds().toString().padStart(2,'0')}.${date.getMilliseconds().toString().padStart(3,'0')}`
        
        state.logList.push({
            time: timeStr,
            message: data.message,
            level: data.level,
            isCrash: data.is_crash
        })
        state.lastLogUpdate = Date.now()
        return
      }

      // Handle Metrics
      const now = new Date(data.timestamp)
      if (data.package) {
        state.currentPackage = data.package
      }
      
      // Buffer Management (Keep ~3600 points = 1 hour)
      if (state.dataBuffer.cpu.length > 3600) {
        state.dataBuffer.cpu.shift()
        state.dataBuffer.memory.shift()
        state.dataBuffer.memoryDetail.shift()
        state.dataBuffer.fps.shift()
        state.dataBuffer.gpu.shift()
        state.dataBuffer.jank.shift()
        state.dataBuffer.stutter.shift()
        state.dataBuffer.batteryTemp.shift()
        state.dataBuffer.network.shift()
      }
      
      state.dataBuffer.cpu.push([now, data.cpu])
      state.dataBuffer.memory.push([now, data.memory])
      state.dataBuffer.memoryDetail.push(data.memory_detail || {})
      state.dataBuffer.fps.push([now, data.fps])
      state.dataBuffer.gpu.push([now, data.gpu || 0])
      state.dataBuffer.jank.push([now, data.jank || 0])
      state.dataBuffer.stutter.push([now, data.stutter || 0])
      state.dataBuffer.batteryTemp.push([now, data.battery ? data.battery.temp : 0])
      state.dataBuffer.network.push([now, data.network || {rx: 0, tx: 0}])
      
      state.lastMetricUpdate = Date.now()
    }

    ws.onerror = (e) => {
      console.error('Store: WS Error:', e)
    }
    
    ws.onclose = (e) => {
      console.log('Store: WS Closed:', e)
      state.isConnected = false
      ws = null
      
      // Auto reconnect
      reconnectTimer = setTimeout(() => {
          console.log('Store: Attempting reconnect...')
          connectWs(serial, target)
      }, 3000)
    }
  }

  const disconnectWs = () => {
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    state.isConnected = false
    if (reconnectTimer) clearTimeout(reconnectTimer)
  }

  const clearData = () => {
    state.dataBuffer = {
      cpu: [], memory: [], memoryDetail: [], fps: [], gpu: [], 
      jank: [], stutter: [], batteryTemp: [], network: []
    }
    state.markers = []
    state.logList = []
    state.screenshotBuffer = []
    state.currentScreenshot = ''
  }

  const addMarker = (label) => {
    state.markers.push({
      time: new Date(),
      label: label || 'Mark'
    })
  }

  return {
    state,
    connectWs,
    disconnectWs,
    clearData,
    addMarker
  }
}
