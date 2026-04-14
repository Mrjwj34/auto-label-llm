<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ECharts, EChartsCoreOption } from 'echarts/core'

type ChartSeries = {
  key: string
  label: string
  color: string
  values: number[]
  format?: 'decimal' | 'percent' | 'integer'
}

const props = defineProps<{
  labels: string[]
  series: ChartSeries[]
  emptyLabel?: string
}>()

const chartHost = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let echartsModule: typeof import('echarts/core') | null = null

const visibleSeries = computed(() =>
  props.series
    .map((series) => ({
      ...series,
      values: series.values.map((value) => (Number.isFinite(value) ? value : null)),
    }))
    .filter((series) => series.values.some((value) => value != null)),
)

const summarySeries = computed(() =>
  visibleSeries.value.map((series) => ({
    ...series,
    latest: [...series.values].reverse().find((value) => value != null) ?? null,
  })),
)

const hasData = computed(() => summarySeries.value.length > 0)

function formatValue(value: number | null, format: ChartSeries['format'] = 'decimal'): string {
  if (value == null) return '--'
  if (format === 'percent') return value.toFixed(2)
  if (format === 'integer') return String(Math.round(value))
  return value.toFixed(4)
}

async function ensureECharts() {
  if (echartsModule) return echartsModule
  const [core, charts, components, renderers] = await Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ])
  core.use([charts.LineChart, components.GridComponent, components.TooltipComponent, renderers.CanvasRenderer])
  echartsModule = core
  return core
}

function buildOption(echarts: typeof import('echarts/core')): EChartsCoreOption {
  const primaryFormat = visibleSeries.value[0]?.format ?? 'decimal'
  return {
    animationDuration: 520,
    animationEasing: 'cubicOut',
    grid: {
      top: 28,
      right: 18,
      bottom: 26,
      left: 40,
      containLabel: false,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#14233a',
      borderWidth: 0,
      padding: 12,
      textStyle: {
        color: '#f8fbff',
        fontFamily: 'IBM Plex Mono, JetBrains Mono, monospace',
      },
      valueFormatter(value: number | string) {
        return formatValue(typeof value === 'number' ? value : null, primaryFormat)
      },
    },
    xAxis: {
      type: 'category',
      data: props.labels,
      boundaryGap: false,
      axisLine: {
        lineStyle: {
          color: 'rgba(106, 126, 152, 0.18)',
        },
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: '#6a7e98',
        fontFamily: 'IBM Plex Mono, JetBrains Mono, monospace',
        fontSize: 11,
      },
    },
    yAxis: {
      type: 'value',
      splitNumber: 4,
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: '#6a7e98',
        fontFamily: 'IBM Plex Mono, JetBrains Mono, monospace',
        fontSize: 11,
        formatter(value: number) {
          return formatValue(value, primaryFormat)
        },
      },
      splitLine: {
        lineStyle: {
          color: 'rgba(106, 126, 152, 0.12)',
          type: 'dashed',
        },
      },
    },
    series: visibleSeries.value.map((series) => ({
      type: 'line',
      name: series.label,
      data: series.values,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 7,
      smooth: true,
      connectNulls: false,
      lineStyle: {
        width: 3,
        color: series.color,
      },
      itemStyle: {
        color: series.color,
      },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: `${series.color}33` },
          { offset: 1, color: `${series.color}00` },
        ]),
      },
      emphasis: {
        focus: 'series',
      },
    })),
  }
}

async function renderChart() {
  await nextTick()
  if (!chartHost.value || !hasData.value) return
  const echarts = await ensureECharts()
  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => {
      chart?.resize()
    })
    resizeObserver.observe(chartHost.value)
  }
  if (!chart) {
    chart = echarts.init(chartHost.value)
  }
  chart.setOption(buildOption(echarts), true)
  chart.resize()
}

function teardownChart() {
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
}

onMounted(async () => {
  await renderChart()
})

watch([hasData, () => props.labels, visibleSeries], async ([nextHasData]) => {
  if (!nextHasData) {
    chart?.clear()
    return
  }
  await renderChart()
}, { deep: true })

onBeforeUnmount(() => {
  teardownChart()
})
</script>

<template>
  <div class="metric-chart">
    <div v-if="!hasData" class="metric-empty">{{ props.emptyLabel ?? '暂无指标数据' }}</div>
    <template v-else>
      <div class="metric-legend">
        <article v-for="item in summarySeries" :key="item.key" class="metric-legend-item">
          <span class="metric-legend-swatch" :style="{ backgroundColor: item.color }" />
          <span>{{ item.label }}</span>
          <strong class="mono">{{ formatValue(item.latest, item.format) }}</strong>
        </article>
      </div>
      <div ref="chartHost" class="metric-canvas" />
    </template>
  </div>
</template>

<style scoped>
.metric-chart {
  display: grid;
  gap: 14px;
}

.metric-empty {
  display: grid;
  place-items: center;
  min-height: 280px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  color: var(--text-muted);
}

.metric-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.metric-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  background: #fff;
  color: var(--text-soft);
}

.metric-legend-swatch {
  width: 10px;
  height: 10px;
}

.metric-canvas {
  min-height: 280px;
  border: 1px solid var(--line);
  background: #f9fbff;
}
</style>
