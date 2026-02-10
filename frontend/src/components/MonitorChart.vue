<script setup>
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, watch, nextTick, computed } from 'vue'
import * as echarts from 'echarts'
import { useMonitorStore } from '../composables/useMonitorStore'

const props = defineProps({
  serial: String,
  active: Boolean,
  target: String
})

const chartRef = ref(null)
let chartInstance = null
const isChartActive = ref(true) // Track visibility
const { state, connectWs, disconnectWs, clearData, addMarker } = useMonitorStore()
const markerLabel = ref('')
const selectedSeriesName = ref('')

const handleAddMarker = () => {
  if (!props.active) {
    alert('请先开始测试')
    return
  }
  const label = prompt('请输入标记名称', markerLabel.value)
  if (label !== null) {
      addMarker(label || 'Marker')
      markerLabel.value = '' // Reset
  }
}

// Use computed for screenshot to stay reactive
const currentScreenshot = computed(() => state.currentScreenshot)

const exportData = () => {
  const dataBuffer = state.dataBuffer
  const headers = ['时间戳', 'CPU(%)', 'GPU(%)', '帧率(FPS)', '卡顿(Jank)', '卡顿率(Stutter%)', '内存(MB)', '电池温度(C)', '网络下行(KB)', '网络上行(KB)']
  const rows = [headers.join(',')]
  
  const formatTime = (date) => {
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const h = String(date.getHours()).padStart(2, '0')
    const min = String(date.getMinutes()).padStart(2, '0')
    const s = String(date.getSeconds()).padStart(2, '0')
    return `${y}${m}${d} ${h}:${min}:${s}`
  }

  const len = dataBuffer.cpu.length
  for (let i = 0; i < len; i++) {
    const time = formatTime(dataBuffer.cpu[i][0])
    const cpu = dataBuffer.cpu[i][1]
    const gpu = dataBuffer.gpu[i] ? dataBuffer.gpu[i][1] : 0
    const fps = dataBuffer.fps[i] ? dataBuffer.fps[i][1] : 0
    const mem = dataBuffer.memory[i] ? dataBuffer.memory[i][1] : 0
    
    // New metrics
    const jank = dataBuffer.jank[i] ? dataBuffer.jank[i][1] : 0
    const stutter = dataBuffer.stutter[i] ? dataBuffer.stutter[i][1] : 0
    const batt = dataBuffer.batteryTemp[i] ? dataBuffer.batteryTemp[i][1] : 0
    
    // Network is cumulative in buffer
    const net = dataBuffer.network[i] ? dataBuffer.network[i][1] : {rx: 0, tx: 0}
    const rx = net.rx || 0
    const tx = net.tx || 0
    
    // Find markers in this second (approx)
    // CSV doesn't support random markers well unless we add a separate column
    // Or we just append them to the last column
    const marker = state.markers.find(m => Math.abs(m.time - dataBuffer.cpu[i][0]) < 1000)
    const markerText = marker ? marker.label : ''

    rows.push(`${time},${cpu},${gpu},${fps},${jank},${stutter},${mem},${batt},${rx},${tx},${markerText}`) 
  }
  
  // Update header
  rows[0] += ',标记(Label)'
  
  // Add BOM for Excel/WPS compatibility
  const blob = new Blob(['\uFEFF' + rows.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  
  // Generate filename with YYYYMMDD_HHMMSS format
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  const h = String(now.getHours()).padStart(2, '0')
  const min = String(now.getMinutes()).padStart(2, '0')
  const s = String(now.getSeconds()).padStart(2, '0')
  const fileTimestamp = `${y}${m}${d}_${h}${min}${s}`
  
  // Include package name in filename if available
  const pkgName = props.target || 'unknown'
  a.download = `perf_data_${pkgName}_${props.serial}_${fileTimestamp}.csv`
  a.click()
}

// 初始化图表配置
let resizeObserver = null

const initChart = () => {
  if (chartInstance) {
    // Check if DOM is disconnected
    if (chartInstance.getDom() !== chartRef.value) {
        chartInstance.dispose()
        chartInstance = null
        if (resizeObserver) {
            resizeObserver.disconnect()
            resizeObserver = null
        }
    } else {
        // Resize just in case
        chartInstance.resize()
        return
    }
  }
  
  if (!chartRef.value) return

  chartInstance = echarts.init(chartRef.value)
  
  // Setup ResizeObserver for robust resizing
  resizeObserver = new ResizeObserver(() => {
      chartInstance?.resize()
  })
  resizeObserver.observe(chartRef.value)
  
  const option = {
    tooltip: { 
      trigger: 'axis',
      order: 'valueDesc', // Sort tooltip by value descending
      confine: true, // Keep tooltip within chart area
      backgroundColor: 'rgba(255, 255, 255, 0.9)', // Semi-transparent
      extraCssText: 'box-shadow: 0 0 8px rgba(0, 0, 0, 0.2); border-radius: 4px;',
      position: function (pos, params, dom, rect, size) {
          // Strictly put in opposite corner to avoid occlusion
          const isRight = pos[0] > size.viewSize[0] / 2;
          return {
              top: 10,
              left: isRight ? 10 : null,
              right: isRight ? null : 120 // Avoid covering the right axis labels/legend
          };
      },
      formatter: (params) => {
        if (params && params.length > 0) {
           const time = params[0].axisValue
           updateScreenshot(time)
           
           let res = new Date(time).toLocaleTimeString() + '<br/>'

           // Add markers info if any match this time
           const timeVal = new Date(time).getTime()
           const marker = state.markers.find(m => Math.abs(m.time.getTime() - timeVal) < 2000)
           if (marker) {
               res += `<span style="color:red;font-weight:bold;display:block;margin-bottom:4px;">🚩 ${marker.label}</span>`
           }
           
           // Sort params by value descending for better visibility
           const sortedParams = [...params].sort((a, b) => (b.value[1] || 0) - (a.value[1] || 0))

           // Add Memory Detail if hovering memory
           const dataIndex = params[0].dataIndex
           const memDetail = state.dataBuffer.memoryDetail[dataIndex]
           
           sortedParams.forEach(item => {
             const value = item.value[1] !== undefined ? item.value[1] : '-'
             // Bold the value
             res += `${item.marker} ${item.seriesName}: <b>${value}</b><br/>`
             
             // If this is the memory series and we have detail
             if (item.seriesName.includes('内存') && memDetail && Object.keys(memDetail).length > 0) {
                 res += `<div style="font-size:10px;color:#aaa;padding-left:15px;margin-bottom:4px;">`
                 if (memDetail.java) res += `Java: ${memDetail.java.toFixed(1)} MB<br/>`
                 if (memDetail.native) res += `Native: ${memDetail.native.toFixed(1)} MB<br/>`
                 if (memDetail.graphics) res += `Graphics: ${memDetail.graphics.toFixed(1)} MB<br/>`
                 if (memDetail.code) res += `Code: ${memDetail.code.toFixed(1)} MB<br/>`
                 if (memDetail.stack) res += `Stack: ${memDetail.stack.toFixed(1)} MB<br/>`
                 res += `</div>`
             }
           })
           return res
        }
        return ''
      }
    },
    legend: { 
      data: ['CPU (%)', 'GPU (%)', '帧率 (FPS)', '卡顿 (Jank)', '卡顿率 (Stutter %)', '内存 (MB)', '电池温度 (°C)'],
      bottom: 0,
      top: 'auto',
      type: 'scroll' 
    },
    grid: { 
      left: '3%', 
      right: '120px',  // Increase right margin for endLabels
      bottom: '15%', 
      top: '12%',    
      containLabel: true 
    },
    dataZoom: [
      {
        type: 'slider',
        show: true,
        xAxisIndex: [0],
        bottom: 5,
        start: 0,
        end: 100
      },
      {
        type: 'inside',
        xAxisIndex: [0],
        start: 0,
        end: 100
      }
    ],
    xAxis: { 
      type: 'time', 
      splitLine: { show: false },
      axisLabel: {
        hideOverlap: true,
        formatter: (value) => {
          const d = new Date(value)
          const h = String(d.getHours()).padStart(2, '0')
          const m = String(d.getMinutes()).padStart(2, '0')
          return `${h}:${m}`
        },
        margin: 12
      }
    },
    yAxis: [
      { type: 'value', name: '使用率 / 帧率', min: 0, nameGap: 15 }, 
      { type: 'value', name: '内存 (MB)', position: 'right', nameGap: 15 }, 
    ],
    series: [
      { 
        name: 'CPU (%)', type: 'line', showSymbol: false, 
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [],
        markLine: {
          symbol: ['none', 'none'],
          label: { show: true, position: 'end', formatter: '{b}' },
          lineStyle: { color: 'red', type: 'dashed' },
          data: []
        }
      },
      { 
        name: 'GPU (%)', type: 'line', showSymbol: false,
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [] 
      },
      { 
        name: '帧率 (FPS)', type: 'line', showSymbol: false,
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [] 
      },
      { 
        name: '卡顿 (Jank)', type: 'bar', stack: 'jank', showSymbol: false,
        emphasis: { focus: 'series' },
        data: [] 
      },
      { 
        name: '卡顿率 (Stutter %)', type: 'line', showSymbol: false,
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [] 
      },
      { 
        name: '内存 (MB)', type: 'line', yAxisIndex: 1, showSymbol: false,
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [] 
      },
      { 
        name: '电池温度 (°C)', type: 'line', showSymbol: false,
        endLabel: { show: false, formatter: '{a}', color: 'inherit' },
        labelLayout: { hideOverlap: true, moveOverlap: 'shiftY' },
        emphasis: { focus: 'series' },
        data: [] 
      }
    ]
  }
  chartInstance.setOption(option)

  const setActiveSeriesLabels = (activeName = '') => {
    const names = [
      'CPU (%)','GPU (%)','帧率 (FPS)','卡顿 (Jank)','卡顿率 (Stutter %)','内存 (MB)','电池温度 (°C)'
    ]
    chartInstance.setOption({
      series: names.map(n => {
        if (n === '卡顿 (Jank)') {
          return { name: n } 
        }
        return { 
          name: n,
          endLabel: { show: activeName && n === activeName }
        }
      })
    })
  }

  // Click handler to select series
  chartInstance.on('click', (params) => {
    if (params.componentType === 'series') {
        selectedSeriesName.value = params.seriesName
        setActiveSeriesLabels(params.seriesName)
        // Optional: Trigger highlight action
        chartInstance.dispatchAction({
            type: 'highlight',
            seriesName: params.seriesName
        })
        
        // Downplay others? ECharts highlight works cumulatively or exclusively depending on impl.
        // For simplicity, we just rely on displaying the name in UI.
    }
  })

  chartInstance.on('mouseover', (params) => {
    if (params.componentType === 'series') {
      setActiveSeriesLabels(params.seriesName)
    }
  })
  chartInstance.on('mouseout', () => {
    setActiveSeriesLabels('')
  })

  // Clear selection when clicking empty area
  chartInstance.getZr().on('click', (params) => {
    if (!params.target) {
        selectedSeriesName.value = ''
        chartInstance.dispatchAction({
            type: 'downplay'
        })
        setActiveSeriesLabels('')
    }
  })
}

// Watch markers to update chart immediately
watch(() => state.markers.length, () => {
    if (chartInstance) {
        const markLineData = state.markers.map(m => ({
            xAxis: m.time,
            label: { formatter: m.label },
            lineStyle: { color: 'red', type: 'dashed' }
        }))
        
        chartInstance.setOption({
            series: [{
                name: 'CPU (%)',
                markLine: {
                    symbol: ['none', 'none'],
                    data: markLineData
                }
            }]
        })
    }
})

const updateScreenshot = (time) => {
    const screenshotBuffer = state.screenshotBuffer
    if (!screenshotBuffer.length) return
    
    // Find closest screenshot
    let closest = screenshotBuffer[0]
    let minDiff = Math.abs(time - closest.time)
    
    for (let i = 1; i < screenshotBuffer.length; i++) {
        const diff = Math.abs(time - screenshotBuffer[i].time)
        if (diff < minDiff) {
            minDiff = diff
            closest = screenshotBuffer[i]
        }
    }
    
    if (minDiff < 3000) { // Only show if within 3 seconds
        state.currentScreenshot = closest.url
    }
}

// Watch lastMetricUpdate to refresh chart
watch(() => state.lastMetricUpdate, () => {
    if (!chartInstance || !isChartActive.value) return
    const dataBuffer = state.dataBuffer
    
    chartInstance.setOption({
      series: [
        { data: dataBuffer.cpu },
        { data: dataBuffer.gpu },
        { data: dataBuffer.fps },
        { data: dataBuffer.jank },
        { data: dataBuffer.stutter },
        { data: dataBuffer.memory },
        { data: dataBuffer.batteryTemp }
      ]
    })
})

watch(() => props.active, (newVal) => {
  if (newVal) {
    clearData() // Clear previous data to avoid mixing sessions
    connectWs(props.serial, props.target)
  } else {
    disconnectWs()
  }
})

watch(() => props.serial, () => {
  if (props.active) {
    disconnectWs()
    connectWs(props.serial, props.target)
  }
  clearData()
  if (chartInstance) {
    chartInstance.setOption({ 
      series: [
        { data: [] }, { data: [] }, { data: [] }, 
        { data: [] }, { data: [] }, { data: [] }, { data: [] }
      ] 
    })
  }
})

onMounted(() => {
  isChartActive.value = true
  nextTick(() => {
    initChart()
    window.addEventListener('resize', () => chartInstance?.resize())
  })
})

onActivated(() => {
  isChartActive.value = true
  nextTick(() => {
    initChart()
    chartInstance?.resize()
    // Force update chart with latest buffer
    if (chartInstance) {
        const dataBuffer = state.dataBuffer
        chartInstance.setOption({
            series: [
                { data: dataBuffer.cpu },
                { data: dataBuffer.gpu },
                { data: dataBuffer.fps },
                { data: dataBuffer.jank },
                { data: dataBuffer.stutter },
                { data: dataBuffer.memory },
                { data: dataBuffer.batteryTemp }
            ]
        })
    }
  })
})

onDeactivated(() => {
  isChartActive.value = false
})

onUnmounted(() => {
  // Don't disconnect here because LogViewer might need the connection
  // disconnectWs() 
  // Actually, if we switch tabs, we want connection to stay. 
  // App.vue keeps <keep-alive> so unmounted won't fire on tab switch.
  // But if user navigates away? Vue 3 unmounted.
  // Since we use keep-alive in App.vue, this component stays mounted.
  chartInstance?.dispose()
  if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
  }
})
</script>

<template>
  <div class="chart-container">
    <div class="chart-header">
      <h3>性能监控</h3>
      <div style="font-size: 12px; color: #666; margin-left: 10px;">
        <span v-if="state.isConnected" style="color: green;">● 连接正常</span>
        <span v-else style="color: red;">● 连接断开</span> |
        <span v-if="selectedSeriesName" style="color: #409eff; font-weight: bold;">👉 {{ selectedSeriesName }} |</span>
        CPU: {{ state.dataBuffer.cpu.slice(-1)[0]?.[1] ?? '-' }}% |
        FPS: {{ state.dataBuffer.fps.slice(-1)[0]?.[1] ?? '-' }} |
        Stutter: {{ state.dataBuffer.stutter.slice(-1)[0]?.[1] ?? '-' }}% |
        Update: {{ new Date(state.lastMetricUpdate).toLocaleTimeString() }}
      </div>
      <div class="btn-group">
        <button @click="handleAddMarker" :disabled="!active" class="marker-btn">🚩 添加标记</button>
        <button @click="exportData" :disabled="state.dataBuffer.cpu.length === 0" class="export-btn">导出 CSV</button>
        <button @click="clearData" class="clear-btn">清空数据</button>
      </div>
    </div>
    <div class="monitor-layout">
      <div ref="chartRef" class="chart"></div>
      <div class="screenshot-panel" v-if="currentScreenshot">
        <h4>屏幕截图</h4>
        <img :src="currentScreenshot" alt="设备截图" class="screenshot-img" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0,0,0,0.1);
  padding: 15px;
  display: flex;
  flex-direction: column;
  position: relative; /* For overlay */
  box-sizing: border-box;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.btn-group {
    display: flex;
    gap: 8px;
}

.btn-group button {
  padding: 4px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: white;
  cursor: pointer;
  font-size: 12px;
}

.btn-group button:disabled {
    cursor: not-allowed;
    color: #c0c4cc;
    background-color: #f5f7fa;
}

.marker-btn {
    background-color: #fdf6ec !important;
    color: #e6a23c;
    border-color: #f5dab1 !important;
}

.marker-btn:hover {
    background-color: #fbf0df !important;
}

.clear-btn {
    color: #f56c6c;
    border-color: #fbc4c4 !important;
    background-color: #fef0f0 !important;
}

.clear-btn:hover {
    background-color: #fde2e2 !important;
}

.export-btn {
    color: #409eff;
    border-color: #b3d8ff !important;
    background-color: #ecf5ff !important;
}

.export-btn:hover {
    background-color: #c6e2ff !important;
}

.monitor-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  width: 100%;
  gap: 10px;
}

.chart {
  flex: 1;
  height: 100%;
  min-width: 0;
}

.screenshot-panel {
  width: 150px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #eee;
  padding-left: 10px;
}

.screenshot-panel h4 {
  margin: 0 0 8px 0;
  font-size: 12px;
  color: #666;
  text-align: center;
}

.screenshot-img {
  width: 100%;
  height: auto;
  border: 1px solid #ddd;
  border-radius: 4px;
}
</style>
