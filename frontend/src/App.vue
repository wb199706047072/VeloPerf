<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import axios from 'axios'
import MonitorChart from './components/MonitorChart.vue'
import LogViewer from './components/LogViewer.vue'
import AnalysisReport from './components/AnalysisReport.vue'
import { useMonitorStore } from './composables/useMonitorStore'

const devices = ref([])
const appList = ref([])
const selectedSerial = ref('')
const targetPackage = ref('')
const isMonitoring = ref(false)
const selectedDevice = ref(null)
const currentTab = ref('monitor') // 'monitor' | 'logs' | 'analysis'
const showAppDropdown = ref(false)
let pollTimer = null
const { state: monitorState } = useMonitorStore()

const filteredApps = computed(() => {
  if (!targetPackage.value) return appList.value
  const lower = targetPackage.value.toLowerCase()
  return appList.value.filter(app => 
    app.name.toLowerCase().includes(lower) || 
    app.package.toLowerCase().includes(lower)
  )
})

const selectApp = (app) => {
  targetPackage.value = app.package
  showAppDropdown.value = false
}

const handleBlur = () => {
  // Delay hide to allow click event to register
  setTimeout(() => {
    showAppDropdown.value = false
  }, 200)
}

const fetchDevices = async (isPoll = false) => {
  try {
    const res = await axios.get('/api/devices')
    const newDevices = res.data.devices
    
    // Check if current device is disconnected
    if (selectedSerial.value) {
        const stillConnected = newDevices.find(d => d.serial === selectedSerial.value)
        if (!stillConnected) {
             if (isMonitoring.value) {
                 isMonitoring.value = false
                 alert('设备已断开连接')
             }
             selectedSerial.value = ''
        }
    }

    devices.value = newDevices
    
    // Auto select first if none selected
    if (devices.value.length > 0 && !selectedSerial.value) {
      selectedSerial.value = devices.value[0].serial
    }
    
    updateSelectedDevice()
    
    if (!isPoll) {
        fetchApps()
    }
  } catch (err) {
    if (!isPoll) console.error(err)
  }
}

const fetchApps = async () => {
  if (!selectedSerial.value) {
      appList.value = []
      return
  }
  try {
    const res = await axios.get(`/api/apps/${selectedSerial.value}`)
    appList.value = res.data.apps
  } catch (err) {
    console.error("Failed to fetch apps", err)
    appList.value = []
  }
}

const updateSelectedDevice = () => {
  selectedDevice.value = devices.value.find(d => d.serial === selectedSerial.value)
}

// Watch selection change
watch(selectedSerial, () => {
  updateSelectedDevice()
  isMonitoring.value = false
  fetchApps()
})

onMounted(() => {
  fetchDevices()
  // Auto refresh device list every 3s
  pollTimer = setInterval(() => fetchDevices(true), 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

const toggleMonitor = () => {
    if (!selectedSerial.value) {
      alert('请先连接并选择设备')
      return
    }

    if (!isMonitoring.value) {
     if (selectedDevice.value?.platform === 'ios' && !targetPackage.value) {
       alert('iOS 设备请填写 Bundle ID')
       return
     }
  }
  isMonitoring.value = !isMonitoring.value
}

watch(() => monitorState.currentPackage, (pkg) => {
  if (!pkg) return
  if (isMonitoring.value && !targetPackage.value) {
    targetPackage.value = pkg
  }
})
</script>

<template>
  <div class="container">
    <header>
      <div class="header-top">
        <h1>VeloPerf 🚀</h1>
        <div class="nav-tabs">
          <div 
            class="tab-item" 
            :class="{ active: currentTab === 'monitor' }"
            @click="currentTab = 'monitor'"
          >
            实时监控
          </div>
          <div 
            class="tab-item" 
            :class="{ active: currentTab === 'logs' }"
            @click="currentTab = 'logs'"
          >
            日志分析
          </div>
          <div 
            class="tab-item" 
            :class="{ active: currentTab === 'analysis' }"
            @click="currentTab = 'analysis'"
          >
            离线分析
          </div>
        </div>
      </div>
      
      <div class="controls" v-if="currentTab === 'monitor'">
        <select v-model="selectedSerial">
          <option v-for="d in devices" :key="d.serial" :value="d.serial">
            {{ d.model }} ({{ d.platform }})
          </option>
        </select>
        
        <div class="input-wrapper">
          <input 
            v-model="targetPackage" 
            type="text"
            placeholder="应用包名 / Bundle ID (可选择或输入)" 
            class="pkg-input"
            @focus="showAppDropdown = true"
            @blur="handleBlur"
          />
          <ul v-if="showAppDropdown && filteredApps.length" class="dropdown-list">
            <li 
              v-for="app in filteredApps" 
              :key="app.package" 
              @click="selectApp(app)"
            >
              {{ app.name }} <span class="pkg-sub">{{ app.package }}</span>
            </li>
          </ul>
        </div>

        <button @click="fetchDevices">刷新设备</button>
        <button @click="toggleMonitor" :class="{ stop: isMonitoring }" :disabled="!selectedSerial && !isMonitoring">
          {{ isMonitoring ? '停止测试' : '开始测试' }}
        </button>
      </div>
    </header>

    <main>
      <keep-alive>
        <MonitorChart 
          v-if="currentTab === 'monitor'"
          :serial="selectedSerial" 
          :active="isMonitoring" 
          :target="targetPackage"
          class="main-content"
        />
        <LogViewer
          v-else-if="currentTab === 'logs'"
          :serial="selectedSerial"
          class="main-content"
        />
        <AnalysisReport 
          v-else-if="currentTab === 'analysis'"
          class="main-content"
        />
      </keep-alive>
      
      <div v-if="currentTab === 'monitor' && !selectedSerial" class="empty-state">
        请连接 USB 设备并开启调试模式。
      </div>
    </main>
  </div>
</template>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;
  box-sizing: border-box;
  gap: 16px;
  background-color: #f0f2f5;
}

header {
  display: flex;
  flex-direction: column;
  gap: 15px;
  background: white;
  padding: 15px 20px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

h1 {
  margin: 0;
  font-size: 24px;
  color: #303133;
}

.nav-tabs {
  display: flex;
  background: #f0f2f5;
  border-radius: 20px;
  padding: 4px;
}

.tab-item {
  padding: 6px 20px;
  cursor: pointer;
  border-radius: 16px;
  font-size: 14px;
  color: #606266;
  transition: all 0.3s;
}

.tab-item.active {
  background: white;
  color: #409eff;
  font-weight: bold;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.input-wrapper {
  position: relative;
}

.pkg-input {
  width: 300px;
  padding: 6px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
}

.dropdown-list {
  position: absolute;
  top: 100%;
  left: 0;
  width: 100%;
  max-height: 300px;
  overflow-y: auto;
  background: white;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0,0,0,0.1);
  margin: 4px 0 0;
  padding: 0;
  list-style: none;
  z-index: 1000;
}

.dropdown-list li {
  padding: 8px 12px;
  cursor: pointer;
  font-size: 14px;
  color: #606266;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid #f0f2f5;
}

.dropdown-list li:last-child {
  border-bottom: none;
}

.dropdown-list li:hover {
  background-color: #f5f7fa;
  color: #409eff;
}

.pkg-sub {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

select {
  padding: 6px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  min-width: 150px;
}

button {
  padding: 6px 16px;
  background-color: #409eff;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.3s;
}

button:hover {
  background-color: #66b1ff;
}

button:disabled {
  background-color: #a0cfff;
  cursor: not-allowed;
}

button.stop {
  background-color: #f56c6c;
}

button.stop:hover {
  background-color: #ff7875;
}

main {
  flex: 1;
  min-height: 0; /* Important for nested flex scroll */
  display: flex;
  flex-direction: column;
}

.main-content {
  flex: 1;
  min-height: 0;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
  font-size: 16px;
}
</style>
