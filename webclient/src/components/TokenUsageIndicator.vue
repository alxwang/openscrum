<template>
  <div v-if="show" class="token-indicator flex items-center gap-2 text-xs">
    <!-- Pie Chart -->
    <div class="relative w-6 h-6">
      <svg class="w-6 h-6 transform -rotate-90" viewBox="0 0 32 32">
        <!-- Background circle -->
        <circle
          cx="16"
          cy="16"
          r="14"
          fill="none"
          :stroke="backgroundColor"
          stroke-width="4"
        />
        <!-- Progress arc -->
        <circle
          cx="16"
          cy="16"
          r="14"
          fill="none"
          :stroke="strokeColor"
          stroke-width="4"
          :stroke-dasharray="circumference"
          :stroke-dashoffset="dashOffset"
          stroke-linecap="round"
          class="transition-all duration-300"
        />
      </svg>
      <!-- Percentage text in center -->
      <div class="absolute inset-0 flex items-center justify-center">
        <span class="text-[8px] font-bold" :style="{ color: strokeColor }">
          {{ Math.round(percentage) }}
        </span>
      </div>
    </div>
    
    <!-- Text info -->
    <div class="flex flex-col">
      <span class="font-medium" :style="{ color: textColor }">
        {{ Math.round(percentage) }}% context used
      </span>
      <span class="text-text-muted text-[10px]">
        {{ formatNumber(tokenCount) }} / {{ formatNumber(tokenLimit) }} tokens
      </span>
    </div>
    
    <!-- Warning icon if high usage -->
    <div v-if="shouldCompress" class="ml-1">
      <svg class="w-4 h-4 text-yellow-500" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
      </svg>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tokenCount: {
    type: Number,
    default: 0,
  },
  tokenLimit: {
    type: Number,
    default: 8192,
  },
  shouldCompress: {
    type: Boolean,
    default: false,
  },
  show: {
    type: Boolean,
    default: true,
  },
})

const percentage = computed(() => {
  if (props.tokenLimit === 0) return 0
  return Math.min((props.tokenCount / props.tokenLimit) * 100, 100)
})

// Circle math for SVG
const radius = 14
const circumference = 2 * Math.PI * radius

const dashOffset = computed(() => {
  const progress = percentage.value / 100
  return circumference * (1 - progress)
})

// Color based on usage percentage
const strokeColor = computed(() => {
  if (percentage.value >= 80) return '#ef4444' // red
  if (percentage.value >= 60) return '#f59e0b' // yellow/orange
  return '#10b981' // green
})

const backgroundColor = computed(() => {
  return '#374151' // gray-700
})

const textColor = computed(() => {
  if (percentage.value >= 80) return '#ef4444' // red
  if (percentage.value >= 60) return '#f59e0b' // yellow/orange
  return '#d1d5db' // gray-300
})

const formatNumber = (num) => {
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + 'M'
  }
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'K'
  }
  return num.toString()
}
</script>

<style scoped>
.token-indicator {
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
