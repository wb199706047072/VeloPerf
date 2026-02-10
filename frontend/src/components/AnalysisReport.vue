<script setup>
import { ref, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const fileInput = ref(null)
const fileName = ref('')
const chartRef = ref(null)
let chartInstance = null
const summary = ref(null)
const conclusion = ref(null)
const tableData = ref([])
const parsedData = ref(null)
const selectedStrategyKey = ref('DEFAULT')

// CSV Column Indices based on export format:
// Time,CPU,GPU,FPS,Jank,Stutter,Memory,Battery,Rx,Tx
const COL_TIME = 0
const COL_CPU = 1
const COL_GPU = 2
const COL_FPS = 3
const COL_JANK = 4
const COL_STUTTER = 5
const COL_MEM = 6
const COL_BATT = 7
const COL_RX = 8
const COL_TX = 9

// Strategy Definitions
const STRATEGIES = {
  GAME: {
    name: '游戏',
    keywords: ['game', 'unity', 'ue4', 'cocos', 'mihoyo', 'tencent', 'netease', 'glory', 'pubg', 'genshin'],
    thresholds: {
      minFps: 30,
      warnFps: 45,
      maxCpu: 400,
      maxMem: 1500,
      jankRate: 10,
      staticCpu: 50
    },
    weights: { fps: 1.5, jank: 2.0, cpu: 0.1 }
  },
  SHOPPING: {
    name: '电商/生活',
    keywords: ['taobao', 'jd', 'pinduoduo', 'mall', 'meituan', 'alipay', 'ctrip', 'dianping'],
    thresholds: {
      minFps: 20,
      warnFps: 40,
      maxCpu: 200,
      maxMem: 800,
      jankRate: 5,
      staticCpu: 100
    },
    weights: { fps: 0.8, jank: 2.5, cpu: 0.2 }
  },
  VIDEO: {
    name: '视频/直播',
    keywords: ['video', 'douyin', 'tiktok', 'kuaishou', 'bilibili', 'youtube', 'youku', 'iqiyi'],
    thresholds: {
      minFps: 24,
      warnFps: 28,
      maxCpu: 150,
      maxMem: 1000,
      jankRate: 5,
      staticCpu: 80
    },
    weights: { fps: 1.0, jank: 2.0, cpu: 0.1 }
  },
  DEFAULT: {
    name: '通用应用',
    keywords: [],
    thresholds: {
      minFps: 24,
      warnFps: 45,
      maxCpu: 150,
      maxMem: 600,
      jankRate: 5,
      staticCpu: 50
    },
    weights: { fps: 1.0, jank: 2.0, cpu: 0.2 }
  }
}

const getStrategy = (fname) => {
  if (!fname) return STRATEGIES.DEFAULT
  const lower = fname.toLowerCase()
  for (const key in STRATEGIES) {
    if (key === 'DEFAULT') continue
    if (STRATEGIES[key].keywords.some(k => lower.includes(k))) {
      return STRATEGIES[key]
    }
  }
  return STRATEGIES.DEFAULT
}

const handleFileUpload = (event) => {
  const file = event.target.files[0]
  if (!file) return
  
  fileName.value = file.name
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target.result
    parseCSV(text)
  }
  reader.readAsText(file)
}

const parseCSV = (text) => {
  const lines = text.split('\n').filter(l => l.trim())
  if (lines.length < 2) {
    alert('无效的 CSV 文件')
    return
  }

  // Check header to ensure format
  // Assume first line is header if it contains letters
  let startIndex = 0
  const headerLine = lines[0].toLowerCase()
  if (headerLine.includes('time') || headerLine.includes('时间戳')) {
    startIndex = 1
  }

  const data = {
    cpu: [], gpu: [], fps: [], jank: [], stutter: [], memory: [], battery: [], networkRx: [], networkTx: []
  }
  
  let totalCpu = 0, totalFps = 0, totalMem = 0, totalGpu = 0
  let maxCpu = 0, maxMem = 0
  let totalJank = 0
  let count = 0
  let startTime = null
  let endTime = null

  // Process lines
  for (let i = startIndex; i < lines.length; i++) {
    const cols = lines[i].split(',')
    if (cols.length < 8) continue // Invalid line

    const timeStr = cols[COL_TIME] // format might be "HH:mm:ss"
    // For chart x-axis, we can just use the string, or convert to index
    // Let's use the string directly for X-axis category or time
    
    // Parse values
    const cpu = parseFloat(cols[COL_CPU]) || 0
    const gpu = parseFloat(cols[COL_GPU]) || 0
    const fps = parseFloat(cols[COL_FPS]) || 0
    const jank = parseFloat(cols[COL_JANK]) || 0
    const stutter = parseFloat(cols[COL_STUTTER]) || 0
    const mem = parseFloat(cols[COL_MEM]) || 0
    const batt = parseFloat(cols[COL_BATT]) || 0
    const rx = parseFloat(cols[COL_RX]) || 0
    const tx = parseFloat(cols[COL_TX]) || 0

    // Stats
    totalCpu += cpu
    totalGpu += gpu
    totalFps += fps
    totalMem += mem
    totalJank += jank
    
    if (cpu > maxCpu) maxCpu = cpu
    if (mem > maxMem) maxMem = mem
    
    count++

    // Chart Data
    data.cpu.push([timeStr, cpu])
    data.gpu.push([timeStr, gpu])
    data.fps.push([timeStr, fps])
    data.jank.push([timeStr, jank])
    data.stutter.push([timeStr, stutter])
    data.memory.push([timeStr, mem])
    data.battery.push([timeStr, batt])
    data.networkRx.push([timeStr, rx])
    data.networkTx.push([timeStr, tx])
    
    if (i === startIndex) startTime = timeStr
    endTime = timeStr
  }

  if (count === 0) return

  // Store parsed data for re-analysis
  parsedData.value = {
    startTime, endTime, count,
    totalCpu, totalFps, totalGpu, totalMem, totalJank,
    maxCpu, maxMem,
    chartData: data
  }

  // Auto-detect strategy
  const strategy = getStrategy(fileName.value)
  // Find key by value
  for (const [key, val] of Object.entries(STRATEGIES)) {
      if (val === strategy) {
          selectedStrategyKey.value = key
          break
      }
  }

  recalculateAnalysis()

  // Wait for DOM update before rendering chart
  nextTick(() => {
    renderChart(data)
  })
}

const recalculateAnalysis = () => {
  if (!parsedData.value) return
  
  const { 
    startTime, endTime, count,
    totalCpu, totalFps, totalGpu, totalMem, totalJank,
    maxCpu, maxMem
  } = parsedData.value

  const strategy = STRATEGIES[selectedStrategyKey.value]

  // Calculate Summary
  const avgFps = (totalFps / count).toFixed(1)
  const avgCpu = (totalCpu / count).toFixed(1)
  const avgGpu = (totalGpu / count).toFixed(1)
  const avgMem = (totalMem / count).toFixed(1)
  
  // Fix: Jank Rate should be (Total Jank Frames / Total Frames) * 100
  let jankRateVal = 0
  if (totalFps > 0) {
      jankRateVal = (totalJank / totalFps) * 100
  }
  
  summary.value = {
    appType: strategy.name,
    duration: `${startTime} ~ ${endTime}`,
    avgFps,
    avgCpu,
    maxCpu: maxCpu.toFixed(1),
    avgGpu,
    avgMem,
    maxMem: maxMem.toFixed(1),
    totalJank: totalJank,
    jankRate: jankRateVal.toFixed(2) + '%'
  }
  
  // Generate Conclusion using Strategy
  const issues = []
  const suggestions = []
  const th = strategy.thresholds
  
  // FPS Analysis
  if (parseFloat(avgFps) < th.minFps) {
    if (totalJank < 5 && parseFloat(avgCpu) < th.staticCpu) { 
        issues.push(`平均帧率较低 (<${th.minFps})，但系统负载低，判定为静态页面或无操作`)
    } else {
        issues.push(`平均帧率过低 (<${th.minFps} FPS)，不满足${strategy.name}流畅度标准`)
        suggestions.push('检查主线程耗时操作，避免在 UI 线程执行 IO 或复杂计算')
        suggestions.push('优化 View 层级，减少 Overdraw（过度绘制）')
    }
  } else if (parseFloat(avgFps) < th.warnFps) {
    issues.push(`平均帧率一般 (<${th.warnFps} FPS)，存在优化空间`)
    suggestions.push('使用 Trace 工具分析渲染瓶颈')
  }
  
  // Jank Analysis
  if (jankRateVal > (th.jankRate * 2)) {
    issues.push(`严重卡顿 (>${th.jankRate * 2}%)，用户体验受损`)
    suggestions.push('定位长耗时帧（Jank Frame），分析是否由 GC 或 Binder 调用引起')
  } else if (jankRateVal > th.jankRate) {
    issues.push(`存在卡顿 (>${th.jankRate}%)，建议排查`)
    suggestions.push('关注卡顿出现的场景，检查是否有瞬时高 CPU 占用')
  }
  
  // CPU Analysis
  if (parseFloat(avgCpu) > th.maxCpu) {
    issues.push(`CPU 平均占用较高 (>${th.maxCpu}%)，可能引起发热降频`)
    suggestions.push('优化后台线程任务，使用线程池管理并发')
    suggestions.push('检查是否有死循环或高频轮询逻辑')
  }
  
  if (maxMem > th.maxMem) {
    issues.push(`内存峰值较高 (>${th.maxMem}MB)，请留意是否存在内存泄漏风险`)
    suggestions.push('使用 Memory Profiler 检查 Bitmap 缓存和对象分配')
    suggestions.push('排查 Activity/Fragment 泄漏')
  }

  if (parseFloat(avgGpu) > 60) {
    suggestions.push('GPU 负载较高，建议优化 Shader 或减少纹理分辨率')
  }
  
  // Score Calculation
  let score = 100
  
  // FPS Deduction
  const isStatic = parseFloat(avgFps) < th.minFps && totalJank < 5 && parseFloat(avgCpu) < th.staticCpu
  if (!isStatic) {
      const fpsTarget = 60
      const fpsDeduction = Math.max(0, (fpsTarget - parseFloat(avgFps)) * strategy.weights.fps)
      score -= Math.min(30, fpsDeduction)
  }
  
  // Jank Deduction
  const jankDeduction = jankRateVal * strategy.weights.jank
  score -= Math.min(40, jankDeduction)
  
  // CPU Deduction
  if (parseFloat(avgCpu) > th.maxCpu) {
      const cpuDeduction = (parseFloat(avgCpu) - th.maxCpu) * strategy.weights.cpu
      score -= Math.min(20, cpuDeduction)
  }
  
  score = Math.max(0, Math.min(100, Math.round(score)))
  
  let grade = '优秀'
  if (score < 90) grade = '良好'
  if (score < 75) grade = '一般'
  if (score < 60) grade = '较差'
  
  conclusion.value = {
      score,
      grade,
      issues: issues.length ? issues : ['整体性能表现平稳，无明显异常'],
      suggestions: suggestions.length ? [...new Set(suggestions)] : ['暂无明显优化建议']
  }
}

const renderChart = (data) => {
  if (chartInstance) {
    chartInstance.dispose()
  }
  
  if (!chartRef.value) return
  
  chartInstance = echarts.init(chartRef.value)
  
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      confine: true,
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      position: function (pos, params, dom, rect, size) {
          // Strictly put in opposite corner to avoid occlusion
          const isRight = pos[0] > size.viewSize[0] / 2;
          return {
              top: 10,
              left: isRight ? 10 : null,
              right: isRight ? null : 10
          };
      },
      formatter: (params) => {
         // Custom formatter to show units
         if (!params.length) return ''
         let res = params[0].axisValue + '<br/>'
         params.forEach(item => {
             const val = item.value[1]
             if (val === undefined) return
             res += `${item.marker} ${item.seriesName}: <b>${val}</b><br/>`
         })
         return res
      }
    },
    legend: { 
      data: ['CPU (%)', 'GPU (%)', '帧率 (FPS)', '卡顿 (Jank)', '卡顿率 (Stutter %)', '内存 (MB)', '电池温度 (°C)', '网络下行 (KB)', '网络上行 (KB)'],
      bottom: 0,
      type: 'scroll'
    },
    grid: { 
      left: '3%', 
      right: '4%', 
      bottom: '15%',
      top: '10%',
      containLabel: true 
    },
    dataZoom: [
      { type: 'slider', show: true, xAxisIndex: 0, bottom: 30 },
      { type: 'inside', xAxisIndex: 0 }
    ],
    xAxis: { 
      type: 'category', // Use category for CSV time strings
      boundaryGap: false 
    },
    yAxis: [
      { type: 'value', name: '使用率 / 帧率', min: 0, nameGap: 15 },
      { type: 'value', name: '内存 (MB) / 网络 (KB)', position: 'right', nameGap: 15 },
    ],
    series: [
      { name: 'CPU (%)', type: 'line', showSymbol: false, data: data.cpu, smooth: true },
      { name: 'GPU (%)', type: 'line', showSymbol: false, data: data.gpu, smooth: true },
      { name: '帧率 (FPS)', type: 'line', showSymbol: false, data: data.fps, smooth: true },
      { name: '卡顿 (Jank)', type: 'bar', stack: 'jank', showSymbol: false, data: data.jank },
      { name: '卡顿率 (Stutter %)', type: 'line', showSymbol: false, data: data.stutter },
      { name: '内存 (MB)', type: 'line', yAxisIndex: 1, showSymbol: false, data: data.memory, smooth: true },
      { name: '电池温度 (°C)', type: 'line', showSymbol: false, data: data.battery },
      { name: '网络下行 (KB)', type: 'line', yAxisIndex: 1, showSymbol: false, data: data.networkRx, lineStyle: { type: 'dashed' } },
      { name: '网络上行 (KB)', type: 'line', yAxisIndex: 1, showSymbol: false, data: data.networkTx, lineStyle: { type: 'dotted' } }
    ]
  }
  
  chartInstance.setOption(option)
}

// Handle window resize
window.addEventListener('resize', () => {
  chartInstance?.resize()
})
</script>

<template>
  <div class="analysis-container">
    <div class="toolbar">
      <div class="upload-box">
        <label for="csv-upload" class="upload-btn">📂 导入 CSV 文件</label>
        <input id="csv-upload" type="file" accept=".csv" @change="handleFileUpload" hidden />
        <span class="file-name">{{ fileName || '未选择文件' }}</span>
      </div>
      
      <div class="strategy-box" v-if="fileName">
          <label>应用类型：</label>
          <select v-model="selectedStrategyKey" @change="recalculateAnalysis">
              <option v-for="(val, key) in STRATEGIES" :key="key" :value="key">
                  {{ val.name }}
              </option>
          </select>
      </div>
    </div>

    <div v-if="summary" class="summary-panel">
      <div class="stat-card">
        <div class="label">Avg FPS</div>
        <div class="value">{{ summary.avgFps }}</div>
      </div>
      <div class="stat-card">
        <div class="label">Jank Total</div>
        <div class="value warn">{{ summary.totalJank }}</div>
      </div>
      <div class="stat-card">
        <div class="label">Avg CPU</div>
        <div class="value">{{ summary.avgCpu }}%</div>
      </div>
      <div class="stat-card">
        <div class="label">Max Memory</div>
        <div class="value">{{ summary.maxMem }} MB</div>
      </div>
      <div class="stat-card">
        <div class="label">Avg GPU</div>
        <div class="value">{{ summary.avgGpu }}%</div>
      </div>
    </div>

    <div class="chart-wrapper">
      <div ref="chartRef" class="chart"></div>
      <div v-if="!summary" class="placeholder">
        请导入 CSV 文件以开始分析
      </div>
    </div>

    <div v-if="conclusion" class="conclusion-panel">
      <div class="score-box">
          <div class="score-circle" :class="getGradeClass(conclusion.grade)">
              <span class="score-num">{{ conclusion.score }}</span>
              <span class="score-grade">{{ conclusion.grade }}</span>
          </div>
      </div>
      <div class="analysis-text">
          <h3>📊 分析结论</h3>
          <ul>
              <li v-for="(issue, i) in conclusion.issues" :key="i">{{ issue }}</li>
          </ul>
      </div>
      <div class="analysis-text" v-if="conclusion.suggestions && conclusion.suggestions.length">
          <h3>💡 优化建议</h3>
          <ul>
              <li v-for="(suggestion, i) in conclusion.suggestions" :key="i">{{ suggestion }}</li>
          </ul>
      </div>
    </div>
  </div>
</template>

<script>
// Helper for class
const getGradeClass = (grade) => {
    if (grade === '优秀') return 'excellent'
    if (grade === '良好') return 'good'
    if (grade === '一般') return 'fair'
    return 'poor'
}
</script>

<style scoped>
.analysis-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 20px;
  background: white;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  overflow-y: auto; /* Allow scrolling if content is too tall */
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 20px;
}

.upload-btn {
  display: inline-block;
  padding: 8px 16px;
  background-color: #409eff;
  color: white;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  transition: 0.3s;
}
.upload-btn:hover {
  background-color: #66b1ff;
}
.file-name {
  margin-left: 10px;
  color: #666;
  font-size: 14px;
}

.summary-panel {
  display: flex;
  gap: 20px;
  padding: 15px;
  background: #f5f7fa;
  border-radius: 6px;
  flex-wrap: wrap;
}

.stat-card {
  background: white;
  padding: 10px 20px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  min-width: 120px;
  text-align: center;
}

.stat-card .label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 5px;
}

.stat-card .value {
  font-size: 20px;
  font-weight: bold;
  color: #303133;
}

.stat-card .value.warn {
  color: #f56c6c;
}

.chart-wrapper {
  flex: 1;
  position: relative;
  min-height: 500px;
  display: flex;
}

.chart {
  width: 100%;
  height: 100%;
}

.placeholder {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #909399;
  font-size: 16px;
}

.conclusion-panel {
  display: flex;
  gap: 30px;
  background: #f8f9fa;
  padding: 20px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.score-box {
    display: flex;
    align-items: center;
    justify-content: center;
}

.score-circle {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: white;
    box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}

.score-circle.excellent { background: linear-gradient(135deg, #67c23a, #95d475); }
.score-circle.good { background: linear-gradient(135deg, #409eff, #79bbff); }
.score-circle.fair { background: linear-gradient(135deg, #e6a23c, #f3d19e); }
.score-circle.poor { background: linear-gradient(135deg, #f56c6c, #fab6b6); }

.score-num { font-size: 24px; font-weight: bold; line-height: 1; }
.score-grade { font-size: 12px; margin-top: 2px; }

.analysis-text h3 { margin: 0 0 10px 0; font-size: 16px; color: #303133; }
.analysis-text ul { padding-left: 20px; margin: 0; color: #606266; font-size: 14px; }
.analysis-text li { margin-bottom: 5px; line-height: 1.5; }

</style>
