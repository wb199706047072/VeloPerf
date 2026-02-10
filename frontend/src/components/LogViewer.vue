<script setup>
import { computed, ref, nextTick, watch, onActivated } from 'vue'
import { useMonitorStore } from '../composables/useMonitorStore'

const props = defineProps({
  serial: String
})

const { state } = useMonitorStore()
const logContainer = ref(null)
const autoScroll = ref(true)

// Computed logs from store
const logs = computed(() => state.logList)

// Watch logs to auto-scroll
watch(() => state.lastLogUpdate, () => {
  if (autoScroll.value) {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
})

onActivated(() => {
  if (autoScroll.value) {
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  }
})

const exportLogs = () => {
  if (state.logList.length === 0) {
    alert('暂无日志')
    return
  }
  
  const lines = state.logList.map(l => `[${l.time}] ${l.message}`)
  // Add BOM for Windows compatibility
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/plain;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  const h = String(now.getHours()).padStart(2, '0')
  const min = String(now.getMinutes()).padStart(2, '0')
  const s = String(now.getSeconds()).padStart(2, '0')
  const fileTimestamp = `${y}${m}${d}_${h}${min}${s}`
  
  a.download = `crash_logs_${props.serial}_${fileTimestamp}.txt`
  a.click()
}

const clearLogs = () => {
  state.logList = []
}
</script>

<template>
  <div class="log-viewer">
    <div class="toolbar">
      <div class="left">
        <h3>系统日志分析</h3>
        <span class="count">共 {{ logs.length }} 条</span>
      </div>
      <div class="right">
        <label class="checkbox">
          <input type="checkbox" v-model="autoScroll"> 自动滚动
        </label>
        <button @click="clearLogs" class="btn clear-btn">清空</button>
        <button @click="exportLogs" class="btn export-btn">导出日志</button>
      </div>
    </div>
    
      <div class="log-container" ref="logContainer">
      <div v-for="(log, index) in logs" :key="index" class="log-item" :class="[`log-${log.level}`, { 'log-crash': log.isCrash }]">
        <span class="log-time">{{ log.time }}</span>
        <span class="log-level-tag">{{ log.level ? log.level.toUpperCase() : 'INFO' }}</span>
        <span class="log-msg">{{ log.message }}</span>
      </div>
      <div v-if="logs.length === 0" class="empty-state">
        暂无日志数据，请在监控页面开始测试...
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  overflow: hidden;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 20px;
  border-bottom: 1px solid #eee;
  background: #f9fafc;
}

.toolbar h3 {
  margin: 0;
  font-size: 16px;
  color: #333;
}

.count {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
  background: #e4e7ed;
  padding: 2px 8px;
  border-radius: 10px;
}

.right {
  display: flex;
  align-items: center;
  gap: 15px;
}

.checkbox {
  font-size: 14px;
  color: #606266;
  display: flex;
  align-items: center;
  cursor: pointer;
}

.checkbox input {
  margin-right: 5px;
}

.btn {
  padding: 6px 16px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.3s;
}

.export-btn {
  background: #409eff;
  color: white;
}
.export-btn:hover {
  background: #66b1ff;
}

.clear-btn {
  background: #f4f4f5;
  color: #909399;
}
.clear-btn:hover {
  background: #e9e9eb;
  color: #606266;
}

.log-container {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  background: #1e1e1e;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
}

.log-item {
  display: flex;
  gap: 10px;
  padding: 4px 8px;
  border-radius: 2px;
  color: #d4d4d4;
  line-height: 1.5;
}

.log-item:hover {
  background: #2d2d2d;
}

.log-time {
  color: #569cd6;
  flex-shrink: 0;
  width: 100px;
}

.log-level-tag {
  flex-shrink: 0;
  width: 60px;
  font-weight: bold;
  text-align: center;
  margin-right: 8px;
  font-size: 12px;
}

.log-msg {
  white-space: pre-wrap;
  word-break: break-all;
}

/* Log Levels */
.log-verbose .log-level-tag { color: #808080; }
.log-debug .log-level-tag { color: #4ec9b0; }
.log-info .log-level-tag { color: #b5cea8; }
.log-warn .log-level-tag { color: #cca700; }
.log-error .log-level-tag { color: #f44336; }

.log-verbose { color: #aaaaaa; }
.log-debug { color: #d4d4d4; }
.log-info { color: #d4d4d4; }
.log-warn { color: #e5e510; }
.log-error { color: #ff7875; }

.log-crash {
  background: rgba(244, 67, 54, 0.2);
  border-left: 3px solid #f44336;
  color: #ff7875;
  font-weight: bold;
}

.empty-state {
  color: #666;
  text-align: center;
  margin-top: 100px;
  font-style: italic;
}
</style>
