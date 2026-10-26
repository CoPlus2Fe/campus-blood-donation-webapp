<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'

const props = defineProps<{ result: number | null; spinKey?: number }>()

const sectors = [
  { value: 10, start: 0, span: 90, color: '#b33848' },
  { value: 15, start: 90, span: 108, color: '#a77436' },
  { value: 20, start: 198, span: 90, color: '#177e75' },
  { value: 25, start: 288, span: 54, color: '#d56150' },
  { value: 30, start: 342, span: 18, color: '#426978' },
]

function point(degrees: number, radius: number) {
  const angle = degrees * Math.PI / 180
  return { x: 120 + radius * Math.sin(angle), y: 120 - radius * Math.cos(angle) }
}
function sectorPath(start: number, span: number) {
  const a = point(start + displayAngle.value, 100)
  const b = point(start + span + displayAngle.value, 100)
  return `M 120 120 L ${a.x} ${a.y} A 100 100 0 ${span > 180 ? 1 : 0} 1 ${b.x} ${b.y} Z`
}
function targetAngle(value: number | null) {
  const sector = sectors.find(item => item.value === value)
  return sector ? 360 - (sector.start + sector.span / 2) : 0
}

const displayAngle = ref(targetAngle(props.result))
let spinFrame: number | undefined
watch(() => props.result, result => {
  if (spinFrame !== undefined) window.cancelAnimationFrame(spinFrame)
  spinFrame = undefined
  displayAngle.value = targetAngle(result)
})
watch(() => props.spinKey, (current, previous) => {
  if (!current || current === previous || props.result === null) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const target = targetAngle(props.result)
  let startedAt: number | undefined
  displayAngle.value = 0
  const tick = (timestamp: number) => {
    startedAt ??= timestamp
    const progress = Math.min((timestamp - startedAt) / 2400, 1)
    displayAngle.value = (1440 + target) * (1 - (1 - progress) ** 4)
    if (progress < 1) spinFrame = window.requestAnimationFrame(tick)
    else { displayAngle.value = target; spinFrame = undefined }
  }
  spinFrame = window.requestAnimationFrame(tick)
})
onUnmounted(() => { if (spinFrame !== undefined) window.cancelAnimationFrame(spinFrame) })
</script>

<template>
  <svg class="wheel-image" viewBox="0 0 240 240" role="img"
       :aria-label="result === null ? '等待抽取的幸运轮' : `指针指向 ${result} 血值的幸运轮结果图`">
    <circle cx="120" cy="120" r="106" fill="#f2cc83" stroke="#784336" stroke-width="3"/>
    <path v-for="sector in sectors" :key="`slice-${sector.value}`" :d="sectorPath(sector.start, sector.span)" :fill="sector.color" stroke="#f7d999" stroke-width="1.4"/>
    <text v-for="sector in sectors" :key="`label-${sector.value}`"
          :x="point(sector.start + sector.span / 2 + displayAngle, 70).x"
          :y="point(sector.start + sector.span / 2 + displayAngle, 70).y"
          text-anchor="middle" dominant-baseline="central" fill="#fff"
          font-size="17" font-weight="800">{{ sector.value }}</text>
    <circle cx="120" cy="120" r="19" fill="#f9e6b9"/>
    <path d="M120 130 C111 123 106 118 109 112 C112 107 118 108 120 112 C123 108 129 107 132 112 C135 118 129 123 120 130Z" fill="#9c2639"/>
    <path d="M108 1 H132 L120 29 Z" fill="#f9e6b9" stroke="#7c463f" stroke-width="1"/>
  </svg>
</template>
