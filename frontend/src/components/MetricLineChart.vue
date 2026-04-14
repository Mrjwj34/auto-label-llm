<script setup lang="ts">
import { computed } from 'vue'

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

const viewWidth = 640
const viewHeight = 260
const chartPadding = {
  top: 18,
  right: 18,
  bottom: 34,
  left: 44,
}

const preparedSeries = computed(() =>
  props.series.map((series) => ({
    ...series,
    values: series.values.filter((value) => Number.isFinite(value)),
  })),
)

const allValues = computed(() => preparedSeries.value.flatMap((series) => series.values))

const domain = computed(() => {
  if (allValues.value.length === 0) {
    return { min: 0, max: 1 }
  }
  const min = Math.min(...allValues.value)
  const max = Math.max(...allValues.value)
  if (min === max) {
    const offset = min === 0 ? 1 : Math.abs(min) * 0.2
    return { min: min - offset, max: max + offset }
  }
  const span = max - min
  return {
    min: Math.max(0, min - span * 0.08),
    max: max + span * 0.1,
  }
})

const innerWidth = viewWidth - chartPadding.left - chartPadding.right
const innerHeight = viewHeight - chartPadding.top - chartPadding.bottom

const gridValues = computed(() => {
  const steps = 4
  const interval = (domain.value.max - domain.value.min) / steps
  return Array.from({ length: steps + 1 }, (_, index) => domain.value.min + interval * index)
})

const displayTicks = computed(() => {
  if (props.labels.length <= 4) {
    return props.labels.map((label, index) => ({ label, index }))
  }
  const indexes = Array.from(new Set([0, Math.floor((props.labels.length - 1) / 2), props.labels.length - 1]))
  return indexes.map((index) => ({ label: props.labels[index] ?? '', index }))
})

function xFor(index: number): number {
  if (props.labels.length <= 1) {
    return chartPadding.left + innerWidth / 2
  }
  return chartPadding.left + (index / (props.labels.length - 1)) * innerWidth
}

function yFor(value: number): number {
  const ratio = (value - domain.value.min) / (domain.value.max - domain.value.min || 1)
  return chartPadding.top + innerHeight - ratio * innerHeight
}

function linePath(values: number[]): string {
  if (values.length === 0) return ''
  return values
    .map((value, index) => `${index === 0 ? 'M' : 'L'} ${xFor(index).toFixed(2)} ${yFor(value).toFixed(2)}`)
    .join(' ')
}

function areaPath(values: number[]): string {
  if (values.length === 0) return ''
  const line = linePath(values)
  const endX = xFor(values.length - 1)
  const startX = xFor(0)
  const baseY = chartPadding.top + innerHeight
  return `${line} L ${endX.toFixed(2)} ${baseY.toFixed(2)} L ${startX.toFixed(2)} ${baseY.toFixed(2)} Z`
}

function formatValue(value: number, format: ChartSeries['format'] = 'decimal'): string {
  if (format === 'percent') return value.toFixed(2)
  if (format === 'integer') return String(Math.round(value))
  return value.toFixed(4)
}
</script>

<template>
  <div class="metric-chart">
    <div v-if="allValues.length === 0" class="metric-empty">{{ props.emptyLabel ?? '暂无指标数据' }}</div>
    <template v-else>
      <div class="metric-legend">
        <div v-for="item in props.series" :key="item.key" class="metric-legend-item">
          <span class="metric-legend-swatch" :style="{ backgroundColor: item.color }" />
          <span>{{ item.label }}</span>
          <strong class="mono">{{ formatValue(item.values[item.values.length - 1] ?? 0, item.format) }}</strong>
        </div>
      </div>

      <svg class="metric-svg" :viewBox="`0 0 ${viewWidth} ${viewHeight}`" role="img" aria-label="指标折线图">
        <g>
          <line
            v-for="gridValue in gridValues"
            :key="gridValue"
            :x1="chartPadding.left"
            :x2="viewWidth - chartPadding.right"
            :y1="yFor(gridValue)"
            :y2="yFor(gridValue)"
            class="metric-grid"
          />
          <text
            v-for="gridValue in gridValues"
            :key="`${gridValue}-label`"
            :x="chartPadding.left - 10"
            :y="yFor(gridValue) + 4"
            class="metric-axis"
            text-anchor="end"
          >
            {{ formatValue(gridValue, props.series[0]?.format) }}
          </text>
        </g>

        <g v-for="item in props.series" :key="item.key">
          <path class="metric-area" :style="{ fill: `${item.color}20` }" :d="areaPath(item.values)" />
          <path class="metric-line" :style="{ stroke: item.color }" :d="linePath(item.values)" />
          <circle
            v-for="(value, index) in item.values"
            :key="`${item.key}-${index}`"
            class="metric-point"
            :style="{ fill: item.color }"
            :cx="xFor(index)"
            :cy="yFor(value)"
            r="3.5"
          />
        </g>

        <g>
          <text
            v-for="tick in displayTicks"
            :key="`tick-${tick.index}`"
            :x="xFor(tick.index)"
            :y="viewHeight - 10"
            class="metric-axis"
            text-anchor="middle"
          >
            {{ tick.label }}
          </text>
        </g>
      </svg>
    </template>
  </div>
</template>

<style scoped>
.metric-chart {
  display: grid;
  gap: 12px;
}

.metric-empty {
  display: grid;
  place-items: center;
  min-height: 240px;
  border: 1px solid var(--line);
  background: var(--panel-soft);
  color: var(--text-muted);
}

.metric-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

.metric-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-soft);
}

.metric-legend-swatch {
  width: 10px;
  height: 10px;
}

.metric-svg {
  width: 100%;
  min-height: 260px;
  border: 1px solid var(--line);
  background:
    linear-gradient(180deg, rgba(11, 95, 255, 0.05), rgba(11, 95, 255, 0)),
    var(--panel-soft);
}

.metric-grid {
  stroke: var(--line);
  stroke-width: 1;
  stroke-dasharray: 3 6;
}

.metric-axis {
  fill: var(--text-muted);
  font-size: 11px;
  font-family: var(--font-mono);
}

.metric-line {
  fill: none;
  stroke-width: 2.5;
  stroke-linejoin: round;
  stroke-linecap: round;
  stroke-dasharray: 1200;
  stroke-dashoffset: 1200;
  animation: metric-draw 900ms ease forwards;
}

.metric-area {
  opacity: 0;
  animation: metric-fade 420ms ease 220ms forwards;
}

.metric-point {
  opacity: 0;
  animation: metric-point-in 240ms ease forwards;
}

@keyframes metric-draw {
  to {
    stroke-dashoffset: 0;
  }
}

@keyframes metric-fade {
  to {
    opacity: 1;
  }
}

@keyframes metric-point-in {
  from {
    opacity: 0;
    transform: scale(0.7);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
